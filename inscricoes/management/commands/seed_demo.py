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
    InscricaoServos, InscricaoCasais,
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
    obj, created = model.objects.get_or_create(**lookup, defaults=defaults or {})
    if not created and defaults:
        dirty = False
        for k, v in defaults.items():
            if getattr(obj, k, None) != v:
                setattr(obj, k, v); dirty = True
        if dirty: obj.save()
    return obj

def mk_periodo(base_day_offset=20, dur=3):
    hoje = date.today()
    di = hoje + timedelta(days=base_day_offset)
    df = di + timedelta(days=dur)
    inicio_ins = hoje - timedelta(days=5)
    fim_ins = di - timedelta(days=1)
    return di, df, inicio_ins, fim_ins

def mirror_booleans_for_status(target: str):
    inscricao_enviada    = target != InscricaoStatus.RASCUNHO
    foi_selecionado      = target in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}
    pagamento_confirmado = target == InscricaoStatus.PAG_CONFIRMADO
    inscricao_concluida  = target == InscricaoStatus.PAG_CONFIRMADO
    return inscricao_enviada, foi_selecionado, pagamento_confirmado, inscricao_concluida

def fast_set_status(ins: Inscricao, target: str):
    inscricao_enviada, foi_sel, pg_conf, ins_conc = mirror_booleans_for_status(target)
    Inscricao.objects.filter(pk=ins.pk).update(
        status=target,
        inscricao_enviada=inscricao_enviada,
        foi_selecionado=foi_sel,
        pagamento_confirmado=pg_conf,
        inscricao_concluida=ins_conc,
    )
    ins.status = target
    ins.inscricao_enviada = inscricao_enviada
    ins.foi_selecionado = foi_sel
    ins.pagamento_confirmado = pg_conf
    ins.inscricao_concluida = ins_conc

def ensure_pagamento_coerente(ins: Inscricao, confirmado: bool, valor: Decimal):
    defaults = {
        "metodo": Pagamento.MetodoPagamento.PIX,
        "valor": valor,
        "status": Pagamento.StatusPagamento.CONFIRMADO if confirmado else Pagamento.StatusPagamento.PENDENTE,
        "data_pagamento": timezone.now() if confirmado else None,
        "transacao_id": f"TX-{uuid.uuid4().hex[:10]}",
        "fee_mp": Decimal("0.00"),
        "net_received": valor if confirmado else Decimal("0.00"),
    }
    pg, created = Pagamento.objects.get_or_create(inscricao=ins, defaults=defaults)
    if not created:
        changed = False
        for k, v in defaults.items():
            if getattr(pg, k) != v:
                setattr(pg, k, v); changed = True
        if changed: pg.save()

# Nomes reais (PT-BR) — simples e suficientes para a demo
SOBRENOMES = [
    "Silva","Santos","Oliveira","Souza","Pereira","Lima","Ferreira","Almeida","Costa","Gomes",
    "Ribeiro","Carvalho","Rocha","Araujo","Barbosa","Cardoso","Correia","Melo","Teixeira","Martins"
]
PRENOMES_M = [
    "João","Pedro","Lucas","Gabriel","Matheus","Rafael","Gustavo","Carlos","Felipe","Henrique",
    "André","Bruno","Diego","Eduardo","Fábio","Leandro","Marcelo","Paulo","Renato","Wagner"
]
PRENOMES_F = [
    "Maria","Ana","Beatriz","Camila","Daniela","Fernanda","Helena","Isabela","Juliana","Larissa",
    "Letícia","Mariana","Natália","Patrícia","Rafaela","Roberta","Sabrina","Tatiane","Vanessa","Yasmin"
]

def nome_completo(prenome, sobrenomes=2):
    return prenome + " " + " ".join(random.sample(SOBRENOMES, k=sobrenomes))

def cpf_demo(prefix: str, seq: int) -> str:
    # 11 dígitos “plausíveis” (validador pode aceitar sem DV real em ambiente demo)
    base = f"{prefix}{seq:09d}"[:11]
    return base

def telefone_demo(seq: int) -> str:
    return f"+5563999{(1000000 + seq):07d}"

def email_demo(prefix: str, seq: int) -> str:
    return f"{prefix}.{seq}@demo.local"

# ---------------------------------------------
# Comando
# ---------------------------------------------
class Command(BaseCommand):
    help = "Seed DEMO: 1 evento de CASAIS (e 1 Servos vinculado), com nomes reais; cria grupos, ministérios, políticas e alocações."

    def add_arguments(self, parser):
        parser.add_argument("--with-users", action="store_true", help="Cria usuários admin/admin_paroquia (senha: admin123).")
        parser.add_argument("--couples", type=int, default=30, help="Quantidade de casais (default: 30).")
        parser.add_argument("--servos", type=int, default=24, help="Quantidade de servos (default: 24).")

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING("==> Seed (casais único)"))

        with_users = opts["with_users"]
        QTD_CASAIS = max(2, int(opts["couples"]))
        QTD_SERVOS = max(4, int(opts["servos"]))

        # ---------------- Paróquia + usuários ----------------
        paroquia = upsert(
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
        if with_users:
            if not User.objects.filter(username="admin").exists():
                User.objects.create_superuser("admin", "admin@sistema.local", "admin123", tipo_usuario="admin_geral")
            if not User.objects.filter(username="paroquia").exists():
                User.objects.create_user("paroquia", "paroquia@sistema.local", "admin123",
                                         tipo_usuario="admin_paroquia", paroquia=paroquia, is_staff=True)

        # ---------------- Site/Políticas ----------------
        upsert(PoliticaPrivacidade, {"id": 1}, {
            "texto": "Sua privacidade é importante. Usamos dados mínimos para operar as inscrições.",
            "cpf_cnpj": "00.000.000/0000-00",
            "email_contato": "contato@eismeaqui.app",
            "telefone_contato": "+5563999991234",
            "endereco": "Praça Central", "numero": "100", "bairro": "Centro", "estado": "TO",
        })
        for nome in ["ECC","RCC","Pastoral do Dízimo","Catequese","Liturgia","Música"]:
            PastoralMovimento.objects.get_or_create(nome=nome)
        SiteImage.objects.get_or_create(key="dashboard", defaults={"titulo": "Dashboard", "categoria": "screenshot"})
        SiteVisit.objects.get_or_create(path="/", ip="127.0.0.1", user_agent="seed/1.0")
        LeadLanding.objects.get_or_create(email="interessado@demo.local",
                                          defaults={"nome":"Interessado","whatsapp":"+5563999912345",
                                                    "mensagem":"Quero saber mais.","consent_lgpd":True,
                                                    "origem":"landing","ip":"127.0.0.1","user_agent":"seed/1.0"})
        CrachaTemplate.objects.get_or_create(nome="Padrão - 4 por página")

        # ---------------- Config MP (FAKE) ----------------
        upsert(MercadoPagoOwnerConfig, {"id": 1}, {
            "nome_exibicao": "Admin do Sistema", "access_token": "MP-OWNER-FAKE",
            "notificacao_webhook_url": "", "email_cobranca": "cobranca@sistema.local", "ativo": True
        })
        MercadoPagoConfig.objects.get_or_create(paroquia=paroquia, defaults={
            "access_token": "MP-PAROQUIA-FAKE", "public_key": "MP-PUB-FAKE", "sandbox_mode": True
        })

        # ---------------- Evento CASAIS (principal) ----------------
        di, df, inicio_ins, fim_ins = mk_periodo(20, 3)
        evento_casais = upsert(EventoAcampamento, {
            "nome": "Encontro de Casais — São José",
            "tipo": "casais",
            "paroquia": paroquia,
        }, {
            "data_inicio": di, "data_fim": df,
            "inicio_inscricoes": inicio_ins, "fim_inscricoes": fim_ins,
            "valor_inscricao": Decimal("200.00"),
            "permitir_inscricao_servos": True,
        })
        VideoEventoAcampamento.objects.get_or_create(evento=evento_casais, defaults={"titulo": "Chamada — Encontro de Casais"})
        PoliticaReembolso.objects.get_or_create(
            evento=evento_casais,
            defaults={"ativo": True, "permite_reembolso": True, "prazo_solicitacao_dias": 7,
                      "taxa_administrativa_percent": Decimal("0.00"),
                      "descricao": "Reembolso integral até 7 dias antes do início.",
                      "contato_email": "financeiro@paroquia.local", "contato_whatsapp": "+5563999900000"}
        )
        Comunicado.objects.get_or_create(paroquia=paroquia, titulo="Aviso importante",
                                         defaults={"texto":"Inscrições abertas para o Encontro de Casais.","publicado":True})
        EventoComunitario.objects.get_or_create(paroquia=paroquia, nome="Feira Solidária",
                                                defaults={"data_inicio": date.today()+timedelta(days=10), "visivel_site": True})

        # ---------------- Evento SERVOS (vinculado ao casais) ----------------
        evento_servos = upsert(EventoAcampamento, {
            "nome": f"Servos – {evento_casais.nome}",
            "tipo": "servos",
            "paroquia": paroquia,
        }, {
            "data_inicio": evento_casais.data_inicio, "data_fim": evento_casais.data_fim,
            "inicio_inscricoes": evento_casais.inicio_inscricoes, "fim_inscricoes": evento_casais.fim_inscricoes,
            "valor_inscricao": Decimal("0.00"),
            "evento_relacionado": evento_casais,
        })
        VideoEventoAcampamento.objects.get_or_create(evento=evento_servos, defaults={"titulo": "Chamada — Servos"})
        PoliticaReembolso.objects.get_or_create(evento=evento_servos, defaults={
            "ativo": True, "permite_reembolso": True, "prazo_solicitacao_dias": 7,
            "taxa_administrativa_percent": Decimal("0.00"),
            "descricao": "Reembolso integral até 7 dias antes do início.",
            "contato_email": "financeiro@paroquia.local", "contato_whatsapp": "+5563999900000"
        })

        # ---------------- Grupos e Ministérios (SERVOS) ----------------
        grupos = []
        for nome, cor in [("Amarelo","#fbbf24"),("Vermelho","#ef4444"),("Azul","#3b82f6"),("Verde","#10b981")]:
            g, _ = Grupo.objects.get_or_create(evento=evento_servos, nome=nome, defaults={"cor": cor})
            grupos.append(g)

        nomes_ministerios = [
            "Liturgia","Música","Intercessão","Cozinha","Ambientação","Comunicação","Apoio","Acolhida","Limpeza","Transporte"
        ]
        ministerios = []
        for nome in nomes_ministerios:
            m, _ = Ministerio.objects.get_or_create(evento=evento_servos, nome=nome, defaults={"descricao": f"Ministério de {nome}"})
            ministerios.append(m)

        # ---------------- Participantes CASAIS ----------------
        # Vamos criar QTD_CASAIS*2 pessoas e parear 1-2, 3-4, ...
        casais_inscricoes = []
        valor = evento_casais.valor_inscricao

        seq = 1
        for i in range(QTD_CASAIS):
            # Pessoa A (masc)
            nomeA = nome_completo(random.choice(PRENOMES_M))
            cpfA = cpf_demo("15", seq); seq += 1
            partA, _ = Participante.objects.get_or_create(
                cpf=cpfA,
                defaults={
                    "nome": nomeA, "telefone": telefone_demo(seq), "email": email_demo("casalA", i+1),
                    "CEP": "77860-000", "endereco": "Rua Principal", "numero": str(100 + i%50),
                    "bairro": "Centro", "cidade": "Wanderlândia", "estado": "TO"
                }
            )
            insA, _ = Inscricao.objects.get_or_create(participante=partA, evento=evento_casais, defaults={"paroquia": paroquia})

            # Pessoa B (fem)
            nomeB = nome_completo(random.choice(PRENOMES_F))
            cpfB = cpf_demo("15", seq); seq += 1
            partB, _ = Participante.objects.get_or_create(
                cpf=cpfB,
                defaults={
                    "nome": nomeB, "telefone": telefone_demo(seq), "email": email_demo("casalB", i+1),
                    "CEP": "77860-000", "endereco": "Rua Principal", "numero": str(100 + (i+7)%50),
                    "bairro": "Centro", "cidade": "Wanderlândia", "estado": "TO"
                }
            )
            insB, _ = Inscricao.objects.get_or_create(participante=partB, evento=evento_casais, defaults={"paroquia": paroquia})

            # cria base InscricaoCasais (se ainda não existir)
            for ins in (insA, insB):
                try:
                    base = getattr(ins, "inscricaocasais", None) or InscricaoCasais.objects.create(inscricao=ins, paroquia=paroquia)
                    if hasattr(base, "tamanho_camisa"):
                        base.tamanho_camisa = random.choice(["P","M","G","GG","XG"])
                        base.save()
                except Exception:
                    pass

            # pareia os dois
            try:
                if hasattr(insA, "set_pareada"):
                    insA.set_pareada(insB)
                else:
                    # fallback: campos OneToOne simétricos, caso existam
                    insA.inscricao_pareada = insB; insA.save(update_fields=["inscricao_pareada"])
                    insB.inscricao_pareada = insA; insB.save(update_fields=["inscricao_pareada"])
            except Exception:
                pass

            # status variados (parte confirmada)
            alvoA = InscricaoStatus.PAG_CONFIRMADO if i % 3 == 0 else (
                InscricaoStatus.PAG_PENDENTE if i % 3 == 1 else InscricaoStatus.ENVIADA
            )
            alvoB = alvoA  # casal espelha status (para simplificar a demo)

            for ins, alvo in [(insA, alvoA), (insB, alvoB)]:
                fast_set_status(ins, alvo)
                if alvo == InscricaoStatus.PAG_CONFIRMADO:
                    ensure_pagamento_coerente(ins, True, valor)
                elif alvo == InscricaoStatus.PAG_PENDENTE:
                    ensure_pagamento_coerente(ins, False, valor)

            casais_inscricoes.extend([insA, insB])

        self.stdout.write(self.style.SUCCESS(f"Casais: {QTD_CASAIS} casais ({len(casais_inscricoes)} inscrições)"))

        # ---------------- Servos (inscrições, grupos, ministérios) ----------------
        servos_inscricoes = []
        for i in range(1, QTD_SERVOS + 1):
            prenome = random.choice(PRENOMES_M + PRENOMES_F)
            nome = nome_completo(prenome)
            cpf = cpf_demo("14", 5000 + i)
            part, _ = Participante.objects.get_or_create(
                cpf=cpf,
                defaults={
                    "nome": nome, "telefone": telefone_demo(5000 + i), "email": email_demo("servo", i),
                    "CEP": "77860-000", "endereco": "Rua Secundária", "numero": str(200 + i%50),
                    "bairro": "Centro", "cidade": "Wanderlândia", "estado": "TO"
                }
            )
            ins, _ = Inscricao.objects.get_or_create(participante=part, evento=evento_servos, defaults={"paroquia": paroquia})
            # base servos
            try:
                base = getattr(ins, "inscricaoservos", None) or InscricaoServos.objects.create(inscricao=ins, paroquia=paroquia)
            except Exception:
                pass

            # status simples (todos convocados; alguns confirmados)
            alvo = InscricaoStatus.PAG_CONFIRMADO if i % 5 == 0 else InscricaoStatus.CONVOCADA
            fast_set_status(ins, alvo)
            if alvo == InscricaoStatus.PAG_CONFIRMADO:
                ensure_pagamento_coerente(ins, True, Decimal("0.00"))
            servos_inscricoes.append(ins)

        # alocar em grupos e ministérios (1 coordenador por ministério)
        for idx, ins in enumerate(servos_inscricoes):
            try:
                AlocacaoGrupo.objects.get_or_create(inscricao=ins, defaults={"grupo": grupos[idx % len(grupos)]})
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

        self.stdout.write(self.style.SUCCESS(f"Servos: {len(servos_inscricoes)} inscrições, grupos e ministérios alocados."))

        # ---------------- Repasse (com base em confirmados) ----------------
        for ev in [evento_casais, evento_servos]:
            total_liquido = Pagamento.objects.filter(
                inscricao__evento=ev, status=Pagamento.StatusPagamento.CONFIRMADO
            ).aggregate(total=Sum("net_received"))["total"] or Decimal("0.00")
            base = total_liquido
            taxa_percent = Decimal("2.00")
            valor_repasse = (base * (Decimal("100.00") - taxa_percent) / Decimal("100.00")).quantize(Decimal("0.01"))
            Repasse.objects.get_or_create(
                paroquia=paroquia, evento=ev, status=Repasse.Status.PENDENTE,
                defaults={"valor_base": base, "taxa_percentual": taxa_percent, "valor_repasse": valor_repasse}
            )

        self.stdout.write(self.style.SUCCESS("==> Seed concluído."))
