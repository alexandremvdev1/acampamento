# inscricoes/management/commands/seed_demo.py
# -*- coding: utf-8 -*-
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum

from inscricoes.models import (
    Paroquia, PastoralMovimento, Participante, EventoAcampamento,
    Inscricao, InscricaoStatus,
    InscricaoSenior, InscricaoJuvenil, InscricaoMirim, InscricaoServos,
    InscricaoCasais, InscricaoEvento, InscricaoRetiro,
    Pagamento, PoliticaReembolso, PoliticaPrivacidade,
    VideoEventoAcampamento, CrachaTemplate,
    MercadoPagoConfig, MercadoPagoOwnerConfig, Repasse,
    SiteImage, SiteVisit, LeadLanding, Comunicado, EventoComunitario,
    Grupo, Ministerio, AlocacaoGrupo, AlocacaoMinisterio
)

User = get_user_model()

# ---------------------------------------------
# Helpers
# ---------------------------------------------
def upsert(model, lookup: dict, defaults: dict = None):
    """get_or_create + update quando necessário; retorna (obj, created_or_updated: bool)."""
    obj, created = model.objects.get_or_create(**lookup, defaults=defaults or {})
    updated = False
    if not created and defaults:
        for k, v in defaults.items():
            if getattr(obj, k, None) != v:
                setattr(obj, k, v)
                updated = True
        if updated:
            obj.save()
    return obj, (created or updated)

TIPO_CODE = {
    "senior": "11", "juvenil": "12", "mirim": "13", "servos": "14",
    "casais": "15", "evento": "16", "retiro": "17", "pagamento": "18"
}

def gen_cpf(tipo_key: str, seq: int) -> str:
    """Gera 11 dígitos aceitos pelo validator (sem DV real, ok para demo)."""
    prefix = TIPO_CODE.get(tipo_key, "99")
    return f"{prefix}{seq:09d}"[:11]

def gen_phone(seq: int) -> str:
    return f"+556399{(9000000 + seq):07d}"

def gen_email(tipo_key: str, seq: int) -> str:
    return f"{tipo_key}.{seq}@example.com"

def mk_periodo(base_day_offset=20, dur=3):
    hoje = date.today()
    di = hoje + timedelta(days=base_day_offset)
    df = di + timedelta(days=dur)
    inicio_ins = hoje - timedelta(days=5)
    fim_ins = di - timedelta(days=1)
    return di, df, inicio_ins, fim_ins

def mirror_booleans_for_status(target: str):
    """Replica a lógica de _espelhar_booleans() do modelo."""
    inscricao_enviada    = target != InscricaoStatus.RASCUNHO
    foi_selecionado      = target in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}
    pagamento_confirmado = target == InscricaoStatus.PAG_CONFIRMADO
    inscricao_concluida  = target == InscricaoStatus.PAG_CONFIRMADO
    return inscricao_enviada, foi_selecionado, pagamento_confirmado, inscricao_concluida

def fast_set_status(ins: Inscricao, target: str):
    """
    Versão ultra-rápida: atualiza status + booleans direto no banco, sem
    percorrer a máquina de estados (evita muitos savepoints).
    Para SEED é ideal; preserve mudar_status() no fluxo normal da app.
    """
    inscricao_enviada, foi_sel, pg_conf, ins_conc = mirror_booleans_for_status(target)
    Inscricao.objects.filter(pk=ins.pk).update(
        status=target,
        inscricao_enviada=inscricao_enviada,
        foi_selecionado=foi_sel,
        pagamento_confirmado=pg_conf,
        inscricao_concluida=ins_conc,
    )
    # mantém objeto em memória coerente (se for usado em seguida)
    ins.status = target
    ins.inscricao_enviada = inscricao_enviada
    ins.foi_selecionado = foi_sel
    ins.pagamento_confirmado = pg_conf
    ins.inscricao_concluida = ins_conc

def ensure_pagamento_coerente(ins: Inscricao, confirmado: bool, valor: Decimal):
    """Garante um Pagamento coerente com o status. Atualiza caso já exista."""
    pay_defaults = {
        "metodo": Pagamento.MetodoPagamento.PIX,
        "valor": valor,
        "status": Pagamento.StatusPagamento.CONFIRMADO if confirmado else Pagamento.StatusPagamento.PENDENTE,
        "data_pagamento": timezone.now() if confirmado else None,
        "transacao_id": f"TX-{uuid.uuid4().hex[:10]}",
        "fee_mp": Decimal("0.00"),
        "net_received": valor if confirmado else Decimal("0.00"),
    }
    pg, created = Pagamento.objects.get_or_create(inscricao=ins, defaults=pay_defaults)
    if not created:
        changed = False
        for k, v in pay_defaults.items():
            if getattr(pg, k) != v:
                setattr(pg, k, v)
                changed = True
        if changed:
            pg.save()

# ---------------------------------------------
# Comando
# ---------------------------------------------
class Command(BaseCommand):
    help = "Popula TUDO: 1 evento de cada tipo com 100 inscrições cada + cadastros auxiliares (rápido)."

    def add_arguments(self, parser):
        parser.add_argument("--with-users", dest="with_users", action="store_true",
                            help="Cria usuários admin_geral e admin_paroquia.")
        parser.add_argument("--email-admin", dest="email_admin", type=str,
                            default="admin@sistema.local")
        parser.add_argument("--email-paroquia", dest="email_paroquia", type=str,
                            default="paroquia@sistema.local")

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING("==> Seed: iniciando (com tudo, fast)"))

        with_users = opts.get("with_users", False)
        email_admin = opts.get("email_admin", "admin@sistema.local")
        email_paroquia = opts.get("email_paroquia", "paroquia@sistema.local")

        # -----------------------------
        # Paróquia + Usuários
        # -----------------------------
        paroquia, _ = upsert(
            Paroquia,
            {"nome": "Paróquia São José"},
            {
                "cidade": "Wanderlândia",
                "estado": "TO",
                "responsavel": "Pe. Islei",
                "email": "paroquia@saojose.local",
                "telefone": "+5563999990000",
                "status": "ativa",
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Paróquia: {paroquia}"))

        if with_users:
            if not User.objects.filter(username="admin").exists():
                User.objects.create_superuser(
                    username="admin",
                    email=email_admin,
                    password="admin123",
                    tipo_usuario="admin_geral",
                )
                self.stdout.write(self.style.SUCCESS("Usuário admin_geral criado (admin/admin123)."))
            if not User.objects.filter(username="paroquia_admin").exists():
                u = User.objects.create_user(
                    username="paroquia_admin",
                    email=email_paroquia,
                    password="admin123",
                    tipo_usuario="admin_paroquia",
                    paroquia=paroquia,
                    is_staff=True,
                )
                self.stdout.write(self.style.SUCCESS(f"Usuário admin_paroquia criado ({u.username}/admin123)."))

        # -----------------------------
        # Pastorais/Movimentos
        # -----------------------------
        for nome in ["ECC", "RCC", "Pastoral do Dízimo", "Catequese", "Liturgia", "Música"]:
            PastoralMovimento.objects.get_or_create(nome=nome)
        self.stdout.write(self.style.SUCCESS("Pastorais/Movimentos ok."))

        # -----------------------------
        # Política de Privacidade / Site assets / Leads / Visitas
        # -----------------------------
        upsert(
            PoliticaPrivacidade,
            {"id": 1},
            {
                "texto": "Sua privacidade é importante. Coletamos dados mínimos para operar as inscrições.",
                "cpf_cnpj": "00.000.000/0000-00",
                "email_contato": "contato@eismeaqui.app",
                "telefone_contato": "+5563999991234",
                "endereco": "Praça Central",
                "numero": "100",
                "bairro": "Centro",
                "estado": "TO",
            },
        )
        SiteImage.objects.get_or_create(key="dashboard", defaults={"titulo": "Dashboard", "categoria": "screenshot"})
        SiteImage.objects.get_or_create(key="pagamentos", defaults={"titulo": "Pagamentos", "categoria": "screenshot"})
        SiteVisit.objects.get_or_create(path="/", ip="127.0.0.1", user_agent="seed/1.0")
        LeadLanding.objects.get_or_create(
            email="alguem@example.com",
            defaults={
                "nome": "Alguém Interessado",
                "whatsapp": "+5563999912345",
                "mensagem": "Quero saber mais do sistema.",
                "consent_lgpd": True,
                "origem": "landing",
                "ip": "127.0.0.1",
                "user_agent": "seed/1.0",
            },
        )
        self.stdout.write(self.style.SUCCESS("Política de Privacidade, mídias, visitas e leads ok."))

        # -----------------------------
        # Eventos: 1 de cada tipo
        # -----------------------------
        tipos = [
            ("senior",   "Acampamento Sênior Demo"),
            ("juvenil",  "Acampamento Juvenil Demo"),
            ("mirim",    "Acampamento Mirim Demo"),
            ("casais",   "Encontro de Casais Demo"),
            ("evento",   "Evento Paroquial Demo"),
            ("retiro",   "Retiro Paroquial Demo"),
            ("pagamento","Evento de Pagamentos Demo"),
        ]
        eventos = {}

        for idx, (tipo, nome) in enumerate(tipos):
            di, df, inicio_ins, fim_ins = mk_periodo(base_day_offset=20 + idx * 3, dur=3)
            defaults = {
                "data_inicio": di,
                "data_fim": df,
                "inicio_inscricoes": inicio_ins,
                "fim_inscricoes": fim_ins,
                "valor_inscricao": Decimal("150.00") if tipo != "pagamento" else Decimal("0.00"),
                "paroquia": paroquia,
            }
            if tipo == "senior":
                defaults["permitir_inscricao_servos"] = True
            ev, _ = upsert(EventoAcampamento, {"nome": nome, "tipo": tipo, "paroquia": paroquia}, defaults)
            eventos[tipo] = ev
            self.stdout.write(self.style.SUCCESS(f"Evento criado/atualizado: {ev}"))

        # Servos vinculado ao SENIOR (via signal)
        ev_servos = eventos["senior"].servos_evento
        if not ev_servos:
            di = eventos["senior"].data_inicio
            df = eventos["senior"].data_fim
            ev_servos, _ = EventoAcampamento.objects.get_or_create(
                nome=f"Servos – {eventos['senior'].nome}",
                tipo="servos",
                paroquia=paroquia,
                defaults={
                    "data_inicio": di,
                    "data_fim": df,
                    "inicio_inscricoes": eventos["senior"].inicio_inscricoes,
                    "fim_inscricoes": eventos["senior"].fim_inscricoes,
                    "valor_inscricao": Decimal("0.00"),
                    "evento_relacionado": eventos["senior"],
                },
            )
        eventos["servos"] = ev_servos
        self.stdout.write(self.style.SUCCESS(f"Evento Servos vinculado: {ev_servos}"))

        # -----------------------------
        # Política de Reembolso, Comunicado, Evento comunitário, Vídeo, Crachá
        # -----------------------------
        for key, ev in eventos.items():
            PoliticaReembolso.objects.get_or_create(
                evento=ev,
                defaults={
                    "ativo": True,
                    "permite_reembolso": True,
                    "prazo_solicitacao_dias": 7,
                    "taxa_administrativa_percent": Decimal("0.00"),
                    "descricao": "Reembolso integral até 7 dias antes do início.",
                    "contato_email": "financeiro@paroquia.local",
                    "contato_whatsapp": "+5563999900000",
                },
            )
        Comunicado.objects.get_or_create(
            paroquia=paroquia,
            titulo="Aviso importante",
            defaults={"texto": "Inscrições abertas para os próximos encontros.", "publicado": True},
        )
        EventoComunitario.objects.get_or_create(
            paroquia=paroquia, nome="Feira Solidária",
            defaults={"data_inicio": date.today() + timedelta(days=10), "visivel_site": True}
        )
        for key, ev in eventos.items():
            VideoEventoAcampamento.objects.get_or_create(evento=ev, defaults={"titulo": f"Chamada — {ev.nome}"})
        CrachaTemplate.objects.get_or_create(nome="Padrão - 4 por página")

        # -----------------------------
        # Mercado Pago: configs (fake de demo)
        # -----------------------------
        upsert(
            MercadoPagoOwnerConfig, {"id": 1},
            {
                "nome_exibicao": "Admin do Sistema",
                "access_token": "MPA-OWNER-ACCESS-TOKEN-FAKE",
                "notificacao_webhook_url": "",
                "email_cobranca": "cobranca@sistema.local",
                "ativo": True,
            },
        )
        MercadoPagoConfig.objects.get_or_create(
            paroquia=paroquia,
            defaults={"access_token": "MPA-PAROQUIA-ACCESS-TOKEN-FAKE", "public_key": "MPA-PAROQUIA-PUBLIC-KEY-FAKE", "sandbox_mode": True},
        )

        # -----------------------------
        # PARTICIPANTES + 100 INSCRIÇÕES por evento
        # -----------------------------
        def criar_participante(tipo_key: str, idx: int) -> Participante:
            cpf = gen_cpf(tipo_key, idx)
            p, _ = Participante.objects.get_or_create(
                cpf=cpf,
                defaults={
                    "nome": f"{tipo_key.capitalize()} Pessoa {idx}",
                    "telefone": gen_phone(idx),
                    "email": gen_email(tipo_key, idx),
                    "CEP": "77860-000",
                    "endereco": "Rua Principal",
                    "numero": str(100 + (idx % 50)),
                    "bairro": "Centro",
                    "cidade": "Wanderlândia",
                    "estado": "TO",
                },
            )
            return p

        def distribuir_status(i: int) -> str:
            # 0-19 confirmados (20), 20-39 pendente (20), 40-49 aprovada (10),
            # 50-59 em análise (10), 60-99 enviada (40)
            if i < 20: return InscricaoStatus.PAG_CONFIRMADO
            if i < 40: return InscricaoStatus.PAG_PENDENTE
            if i < 50: return InscricaoStatus.APROVADA
            if i < 60: return InscricaoStatus.EM_ANALISE
            return InscricaoStatus.ENVIADA

        inscricoes_por_evento = {}

        for tipo_key, ev in eventos.items():
            total = 100
            lista_ins = []
            for i in range(1, total + 1):
                part = criar_participante(tipo_key, i)
                ins, _ = Inscricao.objects.get_or_create(
                    participante=part,
                    evento=ev,
                    defaults={
                        "paroquia": paroquia,
                        "status": InscricaoStatus.RASCUNHO,
                        "ja_e_campista": (i % 7 == 0),
                        "tema_acampamento": "Tema XYZ" if (i % 7 == 0) else "",
                    },
                )
                # base específica
                try:
                    base = ins.ensure_base_instance()
                    if base and hasattr(base, "tamanho_camisa"):
                        base.tamanho_camisa = random.choice(["P", "M", "G", "GG"])
                        base.save()
                except Exception:
                    pass

                alvo = distribuir_status(i)
                # >>> FAST SET aqui (sem mudar_status em cadeia)
                fast_set_status(ins, alvo)

                # pagamentos coerentes
                valor = ev.valor_inscricao or Decimal("0.00")
                if alvo == InscricaoStatus.PAG_CONFIRMADO:
                    ensure_pagamento_coerente(ins, True, Decimal(valor))
                elif alvo == InscricaoStatus.PAG_PENDENTE:
                    ensure_pagamento_coerente(ins, False, Decimal(valor))

                lista_ins.append(ins)

            # Pareamento em CASAIS (1-2, 3-4, …) + se confirmado, propaga ao par
            if tipo_key == "casais":
                for j in range(0, len(lista_ins), 2):
                    a = lista_ins[j]
                    b = lista_ins[j + 1] if (j + 1) < len(lista_ins) else None
                    if not b:
                        break
                    try:
                        # vincula (OneToOne de ambas as pontas via método do modelo)
                        a.set_pareada(b)
                    except Exception:
                        pass
                    # se um dos dois estiver confirmado, garanta os dois confirmados
                    if a.status == InscricaoStatus.PAG_CONFIRMADO and b.status != InscricaoStatus.PAG_CONFIRMADO:
                        fast_set_status(b, InscricaoStatus.PAG_CONFIRMADO)
                        ensure_pagamento_coerente(b, True, Decimal(ev.valor_inscricao or 0))
                    elif b.status == InscricaoStatus.PAG_CONFIRMADO and a.status != InscricaoStatus.PAG_CONFIRMADO:
                        fast_set_status(a, InscricaoStatus.PAG_CONFIRMADO)
                        ensure_pagamento_coerente(a, True, Decimal(ev.valor_inscricao or 0))

            inscricoes_por_evento[tipo_key] = lista_ins
            self.stdout.write(self.style.SUCCESS(f"{ev.nome}: {len(lista_ins)} inscrições prontas."))

        # -----------------------------
        # Servos: Grupos / Ministérios / Alocações
        # -----------------------------
        ev_sv = eventos.get("servos")
        if ev_sv:
            grupos = []
            for nome in ["Amarelo", "Vermelho", "Azul", "Verde"]:
                g, _ = Grupo.objects.get_or_create(evento=ev_sv, nome=nome, defaults={"cor": nome})
                grupos.append(g)

            ministerios = []
            for nome in ["Liturgia", "Música", "Intercessão", "Cozinha"]:
                m, _ = Ministerio.objects.get_or_create(
                    evento=ev_sv, nome=nome, defaults={"descricao": f"Ministério de {nome}"}
                )
                ministerios.append(m)

            servos_ins = inscricoes_por_evento.get("servos", [])[:60]
            for idx, ins in enumerate(servos_ins):
                try:
                    AlocacaoGrupo.objects.get_or_create(
                        inscricao=ins,
                        defaults={"grupo": grupos[idx % len(grupos)]},
                    )
                except Exception:
                    pass
                try:
                    min_ref = ministerios[idx % len(ministerios)]
                    is_coord = not AlocacaoMinisterio.objects.filter(ministerio=min_ref, is_coordenador=True).exists()
                    AlocacaoMinisterio.objects.get_or_create(
                        inscricao=ins,
                        defaults={"ministerio": min_ref, "funcao": "Serviço", "is_coordenador": is_coord},
                    )
                except Exception:
                    pass
            self.stdout.write(self.style.SUCCESS("Servos: grupos, ministérios e alocações criados."))

        # -----------------------------
        # REPASSE (baseado no confirmado)
        # -----------------------------
        for tipo_key, ev in eventos.items():
            total_liquido = Pagamento.objects.filter(
                inscricao__evento=ev,
                status=Pagamento.StatusPagamento.CONFIRMADO,
            ).aggregate(total=Sum("net_received"))["total"] or Decimal("0.00")

            base = total_liquido
            taxa_percent = Decimal("2.00")
            valor_repasse = (base * (Decimal("100.00") - taxa_percent) / Decimal("100.00")).quantize(Decimal("0.01"))

            Repasse.objects.get_or_create(
                paroquia=paroquia,
                evento=ev,
                status=Repasse.Status.PENDENTE,
                defaults={
                    "valor_base": base,
                    "taxa_percentual": taxa_percent,
                    "valor_repasse": valor_repasse,
                },
            )
        self.stdout.write(self.style.SUCCESS("Repasses gerados (pendentes)."))

        self.stdout.write(self.style.SUCCESS("==> Seed concluído com sucesso (fast)."))
