# -*- coding: utf-8 -*-
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from inscricoes.models import (
    Paroquia, PastoralMovimento, Participante, EventoAcampamento,
    Inscricao, InscricaoStatus, Pagamento,
    PoliticaPrivacidade, PoliticaReembolso, VideoEventoAcampamento, CrachaTemplate,
    Grupo, Ministerio, AlocacaoGrupo, AlocacaoMinisterio
)

User = get_user_model()

# ---- cidades variadas do Tocantins ----
CIDADES_TO = [
    "Palmas","Araguaína","Gurupi","Porto Nacional","Paraíso do Tocantins",
    "Colinas do Tocantins","Dianópolis","Guaraí","Miracema do Tocantins",
    "Tocantinópolis","Wanderlândia","Formoso do Araguaia","Pedro Afonso",
    "Caseara","Pium","Lagoa da Confusão","Araguatins","Augustinópolis",
    "Xambioá","Pequizeiro",
]

# nomes curtos pra não estourar o slug (SlugField default = 50)
NOME_CASAIS = "EC São José 2025"       # curto
NOME_SERVOS = "Servos EC São José 25"  # curto

def periodo(offset_dias=20, dur=3):
    hoje = date.today()
    di = hoje + timedelta(days=offset_dias)
    df = di + timedelta(days=dur)
    inicio_ins = hoje - timedelta(days=5)
    fim_ins = di - timedelta(days=1)
    return di, df, inicio_ins, fim_ins

def cpf_fake(i: int) -> str:
    # 11 dígitos simples para demo
    return f"15{i:09d}"[:11]

def ensure_pagamento(ins, confirmado: bool, valor: Decimal):
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
                setattr(pg, k, v)
                changed = True
        if changed:
            pg.save()

def fast_status(ins: Inscricao, target: str):
    enviada = target != InscricaoStatus.RASCUNHO
    sel = target in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}
    conf = target == InscricaoStatus.PAG_CONFIRMADO
    conc = conf
    Inscricao.objects.filter(pk=ins.pk).update(
        status=target,
        inscricao_enviada=enviada,
        foi_selecionado=sel,
        pagamento_confirmado=conf,
        inscricao_concluida=conc,
    )
    ins.status = target
    ins.inscricao_enviada = enviada
    ins.foi_selecionado = sel
    ins.pagamento_confirmado = conf
    ins.inscricao_concluida = conc

class Command(BaseCommand):
    help = "Seed: 1 evento de CASAIS + evento de SERVOS (auto-vinculado), casais com cidades variadas do TO, grupos/ministérios/alocações."

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING("==> Seed (casais único)"))

        # Paróquia
        paroquia, _ = Paroquia.objects.get_or_create(
            nome="Paróquia São José",
            defaults={
                "cidade": "Wanderlândia",
                "estado": "TO",
                "responsavel": "Pe. Islei",
                "email": "paroquia@saojose.local",
                "telefone": "+5563999990000",
                "status": "ativa",
            },
        )

        # Admin
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                email="admin@sistema.local",
                password="admin123",
                tipo_usuario="admin_geral",
            )

        PoliticaPrivacidade.objects.get_or_create(
            id=1, defaults={"texto": "Política de privacidade (demo)."}
        )
        CrachaTemplate.objects.get_or_create(nome="Padrão - 4 por página")

        for nome in ["ECC", "RCC", "Pastoral do Dízimo", "Catequese", "Liturgia", "Música"]:
            PastoralMovimento.objects.get_or_create(nome=nome)

        # ===== evento CASAIS (nome curto para slug não estourar) =====
        di, df, inicio_ins, fim_ins = periodo(20, 3)
        evento_casais, _ = EventoAcampamento.objects.get_or_create(
            nome=NOME_CASAIS,
            tipo="casais",
            paroquia=paroquia,
            defaults={
                "data_inicio": di,
                "data_fim": df,
                "inicio_inscricoes": inicio_ins,
                "fim_inscricoes": fim_ins,
                "valor_inscricao": Decimal("150.00"),
                "permitir_inscricao_servos": True,  # libera inscrições no servos
            },
        )
        # garante flag mesmo se o evento já existia
        if not getattr(evento_casais, "permitir_inscricao_servos", False):
            evento_casais.permitir_inscricao_servos = True
            evento_casais.save(update_fields=["permitir_inscricao_servos"])

        PoliticaReembolso.objects.get_or_create(
            evento=evento_casais,
            defaults={
                "ativo": True,
                "permite_reembolso": True,
                "prazo_solicitacao_dias": 7,
                "descricao": "Reembolso integral até 7 dias antes do início.",
            }
        )
        VideoEventoAcampamento.objects.get_or_create(
            evento=evento_casais, defaults={"titulo": f"Chamada — {NOME_CASAIS}"}
        )

        # ===== evento SERVOS: vem do post_save; se não veio, criamos curto =====
        evento_servos = evento_casais.servos_evento
        if not evento_servos:
            evento_servos, _ = EventoAcampamento.objects.get_or_create(
                nome=NOME_SERVOS,
                tipo="servos",
                paroquia=paroquia,
                defaults={
                    "data_inicio": di,
                    "data_fim": df,
                    "inicio_inscricoes": inicio_ins,
                    "fim_inscricoes": fim_ins,
                    "valor_inscricao": Decimal("0.00"),
                    "evento_relacionado": evento_casais,
                },
            )

        PoliticaReembolso.objects.get_or_create(
            evento=evento_servos,
            defaults={"ativo": True, "permite_reembolso": False, "prazo_solicitacao_dias": 0}
        )
        VideoEventoAcampamento.objects.get_or_create(
            evento=evento_servos, defaults={"titulo": f"Chamada — {NOME_SERVOS}"}
        )

        # ===== nomes de pessoas (reais/inteiros) =====
        nomes_masc = [
            "Carlos Eduardo Almeida","João Pedro Ferreira","Lucas Menezes",
            "Rafael Souza","Gustavo Martins","Bruno Oliveira","André Santos",
            "Marcelo Ribeiro","Thiago Carvalho","Paulo Henrique Lima",
        ]
        nomes_fem = [
            "Ana Carolina Pereira","Mariana Rocha","Fernanda Alves",
            "Juliana Barros","Camila Duarte","Patrícia Nogueira","Larissa Pinto",
            "Renata Teixeira","Aline Moreira","Roberta Figueiredo",
        ]

        # ===== inscrições de CASAIS (20 casais = 40 pessoas) =====
        casais = []
        total_casais = 20
        for i in range(total_casais):
            nm = nomes_masc[i % len(nomes_masc)]
            nf = nomes_fem[i % len(nomes_fem)]
            cidade = CIDADES_TO[i % len(CIDADES_TO)]

            p1, _ = Participante.objects.get_or_create(
                cpf=cpf_fake(i*2 + 1),
                defaults={
                    "nome": nm, "telefone": f"+5563999{i:07d}",
                    "email": f"casal{i+1}.ele@example.com",
                    "CEP": "77860-000", "endereco": "Rua Principal", "numero": "100",
                    "bairro": "Centro", "cidade": cidade, "estado": "TO",
                },
            )
            p2, _ = Participante.objects.get_or_create(
                cpf=cpf_fake(i*2 + 2),
                defaults={
                    "nome": nf, "telefone": f"+5563998{i:07d}",
                    "email": f"casal{i+1}.ela@example.com",
                    "CEP": "77860-000", "endereco": "Rua Principal", "numero": "100",
                    "bairro": "Centro", "cidade": cidade, "estado": "TO",
                },
            )

            ins1, _ = Inscricao.objects.get_or_create(
                participante=p1, evento=evento_casais,
                defaults={"paroquia": paroquia, "status": InscricaoStatus.ENVIADA}
            )
            ins2, _ = Inscricao.objects.get_or_create(
                participante=p2, evento=evento_casais,
                defaults={"paroquia": paroquia, "status": InscricaoStatus.ENVIADA}
            )

            # pareia (método do modelo cuida dos dois lados)
            try:
                ins1.set_pareada(ins2)
            except Exception:
                pass

            # 8 casais confirmados, 4 pendentes, 8 enviados
            if i < 8:
                alvo = InscricaoStatus.PAG_CONFIRMADO
            elif i < 12:
                alvo = InscricaoStatus.PAG_PENDENTE
            else:
                alvo = InscricaoStatus.ENVIADA

            for ins in (ins1, ins2):
                fast_status(ins, alvo)
                if alvo in (InscricaoStatus.PAG_CONFIRMADO, InscricaoStatus.PAG_PENDENTE):
                    ensure_pagamento(
                        ins,
                        confirmado=(alvo == InscricaoStatus.PAG_CONFIRMADO),
                        valor=evento_casais.valor_inscricao or Decimal("0.00"),
                    )

            casais.append((ins1, ins2))

        # ===== SERVOS: grupos, ministérios, alocações =====
        grupos = []
        for nome in ["Amarelo", "Vermelho", "Azul", "Verde"]:
            g, _ = Grupo.objects.get_or_create(evento=evento_servos, nome=nome, defaults={"cor": nome})
            grupos.append(g)

        ministerios = []
        for nome in ["Liturgia", "Música", "Intercessão", "Cozinha", "Ambientação", "Acolhida"]:
            m, _ = Ministerio.objects.get_or_create(
                evento=evento_servos,
                nome=nome,
                defaults={"descricao": f"Ministério de {nome}"}
            )
            ministerios.append(m)

        # usa 8 casais (16 pessoas) como servos
        servos_fontes = []
        for k in range(8):
            servos_fontes.extend([casais[k][0], casais[k][1]])

        for idx, src_ins in enumerate(servos_fontes):
            p = src_ins.participante
            ins_sv, _ = Inscricao.objects.get_or_create(
                participante=p, evento=evento_servos,
                defaults={"paroquia": paroquia, "status": InscricaoStatus.CONVOCADA}
            )
            # aloca grupo
            AlocacaoGrupo.objects.get_or_create(
                inscricao=ins_sv,
                defaults={"grupo": grupos[idx % len(grupos)]},
            )
            # aloca ministério (um coordenador por ministério)
            mref = ministerios[idx % len(ministerios)]
            is_coord = not AlocacaoMinisterio.objects.filter(ministerio=mref, is_coordenador=True).exists()
            AlocacaoMinisterio.objects.get_or_create(
                inscricao=ins_sv,
                defaults={"ministerio": mref, "funcao": "Serviço", "is_coordenador": is_coord},
            )

        self.stdout.write(self.style.SUCCESS("OK: Casais (cidades TO) + Servos, grupos, ministérios e alocações criados."))
        self.stdout.write(self.style.SUCCESS("Login admin/admin123 (se necessário)."))
