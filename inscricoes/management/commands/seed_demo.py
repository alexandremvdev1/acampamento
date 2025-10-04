# -*- coding: utf-8 -*-
import uuid
import random
import re
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from inscricoes.models import (
    Paroquia, PastoralMovimento, Participante, EventoAcampamento,
    Inscricao, InscricaoStatus, Pagamento,
    PoliticaPrivacidade, PoliticaReembolso, VideoEventoAcampamento, CrachaTemplate,
    Grupo, Ministerio, AlocacaoGrupo, AlocacaoMinisterio,
)

User = get_user_model()

# ---------------------- helpers ----------------------
def periodo(offset_dias=20, dur=3):
    hoje = date.today()
    di = hoje + timedelta(days=offset_dias)
    df = di + timedelta(days=dur)
    inicio_ins = hoje - timedelta(days=5)
    fim_ins = di - timedelta(days=1)
    return di, df, inicio_ins, fim_ins

def cpf_mask(digs: str) -> str:
    d = re.sub(r"\D", "", digs)[:11]
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}"

def cpf_fake(i: int) -> str:
    # 11 dígitos simples para demo (únicos)
    d = f"15{i:09d}"[:11]
    return cpf_mask(d)

def ensure_pagamento(ins: Inscricao, confirmado: bool, valor: Decimal):
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

# ---------- nomes realistas brasileiros (únicos e variados) ----------
FIRST_MALE = [
    "Alexandre","Carlos","João","Lucas","Rafael","Gustavo","Bruno","André","Marcelo","Thiago",
    "Paulo","Pedro","Felipe","Diego","Eduardo","Henrique","Leandro","Rodrigo","Roberto","Mateus",
    "Caio","Daniel","Murilo","Vitor","Fábio","Gabriel","Ícaro","Leonardo","Marcos","Rogério",
]
FIRST_FEMALE = [
    "Ana","Mariana","Fernanda","Juliana","Camila","Patrícia","Larissa","Renata","Aline","Roberta",
    "Carolina","Bianca","Beatriz","Bruna","Daniela","Elaine","Isabela","Letícia","Michele","Natália",
    "Paula","Priscila","Rafaela","Sabrina","Simone","Talita","Vanessa","Viviane","Yasmin","Kelly",
]
PARTICULAS = ["da", "de", "do", "dos", "das"]
SURNAMES_POOL = [
    "Silva","Souza","Santos","Oliveira","Pereira","Lima","Carvalho","Ribeiro","Almeida","Gomes","Martins",
    "Araújo","Barbosa","Cardoso","Castro","Correia","Costa","Dias","Duarte","Ferreira","Fernandes",
    "Garcia","Gonçalves","Mendes","Moura","Nogueira","Pires","Rocha","Rodrigues","Santiago","Teixeira",
    "Vieira","Moraes","Barros","Batista","Campos","Figueiredo","Machado","Monteiro","Moreira","Macedo",
    "Ramos","Rezende","Tavares","Matos","Peixoto","Queiroz","Sales","Xavier","Aquino","Bezerra",
    "Cavalcante","Chaves","Coelho","Coutinho","Dantas","Freitas","Leite","Melo","Mesquita","Prado",
    "Santana","Silveira","Soares","Valente","Vasconcelos","Viana","Menezes","Pinheiro","Assis","Aguiar",
    "Cunha","Nunes","Pimentel","Barreto","Borges","Camargo","Farias","Franco","Junior","Lopes",
]

def gerar_nome_realista(genero: str, usados: set[str]) -> str:
    first = random.choice(FIRST_MALE if genero.upper() == "M" else FIRST_FEMALE)
    s1, s2 = random.sample(SURNAMES_POOL, 2)
    if random.random() < 0.40:
        part = random.choice(PARTICULAS)
        full = f"{first} {s1} {part} {s2}"
    else:
        full = f"{first} {s1} {s2}"
    return full if full not in usados else gerar_nome_realista(genero, usados)

def gerar_lote_nomes(qtd: int, genero: str) -> list[str]:
    usados = set(Participante.objects.values_list("nome", flat=True))
    out = []
    while len(out) < qtd:
        nome = gerar_nome_realista(genero, usados)
        usados.add(nome)
        out.append(nome)
    return out

# ---------- ministérios padrão / grupos com cores ----------
MINISTERIOS_PADRAO = [
    "Liturgia","Música","Intercessão","Cozinha","Ambientação","Acolhida",
    "Secretaria","Comunicação","Fotografia","Transporte","Limpeza","Apoio",
    "Financeiro","Segurança","Crianças","Saúde/Enfermaria",
]

GRUPOS_CORES = {
    "Amarelo":  "#FDE047",  # yellow-300
    "Vermelho": "#EF4444",  # red-500
    "Azul":     "#3B82F6",  # blue-500
    "Verde":    "#22C55E",  # green-500
}

# nomes curtos (evita slug gigante)
NOME_CASAIS = "EC São José 2025"
NOME_SERVOS = "Servos EC São José 25"

# ======================================================
class Command(BaseCommand):
    help = "Seed: evento de CASAIS + SERVOS; nomes realistas; casais pareados; grupos/ministérios globais; alocações; pagamentos."

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

        # Admin (superuser)
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                email="admin@sistema.local",
                password="admin123",
                tipo_usuario="admin_geral",
            )

        # Itens institucionais úteis
        PoliticaPrivacidade.objects.get_or_create(id=1, defaults={"texto": "Política de privacidade (demo)."})
        CrachaTemplate.objects.get_or_create(nome="Padrão - 4 por página")

        for nome in ["ECC", "RCC", "Pastoral do Dízimo", "Catequese", "Liturgia", "Música"]:
            PastoralMovimento.objects.get_or_create(nome=nome)

        # ===== evento CASAIS =====
        di, df, inicio_ins, fim_ins = periodo(20, 3)
        slug_curto = f"casais-sao-jose-{di:%Y-%m-%d}"[:50]
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
                "permitir_inscricao_servos": True,
                "slug": slug_curto,  # evita exceder 50 chars
            },
        )
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

        # ===== evento SERVOS (se o sinal não criou, garante aqui) =====
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
                    "slug": f"servos-sao-jose-{di:%Y-%m-%d}"[:50],
                },
            )
        PoliticaReembolso.objects.get_or_create(
            evento=evento_servos,
            defaults={"ativo": True, "permite_reembolso": False, "prazo_solicitacao_dias": 0}
        )
        VideoEventoAcampamento.objects.get_or_create(
            evento=evento_servos, defaults={"titulo": f"Chamada — {NOME_SERVOS}"}
        )

        # ===== nomes completos, variados e únicos (40 pessoas) =====
        random.seed()
        nomes_homens = gerar_lote_nomes(20, 'M')
        nomes_mulheres = gerar_lote_nomes(20, 'F')

        # ===== inscrições de CASAIS (20 casais = 40 pessoas) =====
        casais = []
        total_casais = 20
        for i in range(total_casais):
            nm = nomes_homens[i]
            nf = nomes_mulheres[i]
            cidade = [
                "Palmas","Araguaína","Gurupi","Porto Nacional","Paraíso do Tocantins",
                "Colinas do Tocantins","Dianópolis","Guaraí","Miracema do Tocantins",
                "Tocantinópolis","Wanderlândia","Formoso do Araguaia","Pedro Afonso",
                "Caseara","Pium","Lagoa da Confusão","Araguatins","Augustinópolis",
                "Xambioá","Pequizeiro",
            ][i % 20]

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

            # parear (modelo garante bidirecional)
            try:
                ins1.set_pareada(ins2)
            except Exception:
                pass

            # 8 casais confirmados, 4 pendentes, 8 só enviados
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

        # ===== GRUPOS (globais) com cores =====
        grupos = []
        for nome, cor_hex in GRUPOS_CORES.items():
            g, created = Grupo.objects.get_or_create(
                nome=nome,
                defaults={"cor_nome": nome, "cor_hex": cor_hex}
            )
            to_update = []
            if g.cor_hex != cor_hex:
                g.cor_hex = cor_hex; to_update.append("cor_hex")
            if g.cor_nome != nome:
                g.cor_nome = nome; to_update.append("cor_nome")
            if to_update:
                g.save(update_fields=to_update)
            grupos.append(g)

        # ===== MINISTÉRIOS (globais) =====
        ministerios = []
        for nome in MINISTERIOS_PADRAO:
            m, created = Ministerio.objects.get_or_create(
                nome=nome,
                defaults={"descricao": f"Ministério de {nome}"}
            )
            if not created and not (m.descricao or "").strip():
                m.descricao = f"Ministério de {nome}"
                m.save(update_fields=["descricao"])
            ministerios.append(m)

        # ===== SERVOS: usa 8 casais (16 pessoas) como servos do evento de servos =====
        servos_fontes = []
        for k in range(8):
            servos_fontes.extend([casais[k][0], casais[k][1]])

        for idx, src_ins in enumerate(servos_fontes):
            p = src_ins.participante
            ins_sv, _ = Inscricao.objects.get_or_create(
                participante=p, evento=evento_servos,
                defaults={"paroquia": paroquia, "status": InscricaoStatus.CONVOCADA}
            )
            # Alocação de grupo (round-robin) — precisa do evento nos defaults
            AlocacaoGrupo.objects.get_or_create(
                inscricao=ins_sv,
                defaults={
                    "evento": evento_servos,
                    "grupo": grupos[idx % len(grupos)],
                },
            )
            # Alocação de ministério (garante um coordenador por (evento, ministério))
            mref = ministerios[idx % len(ministerios)]
            is_coord = not AlocacaoMinisterio.objects.filter(
                evento=evento_servos, ministerio=mref, is_coordenador=True
            ).exists()
            AlocacaoMinisterio.objects.get_or_create(
                inscricao=ins_sv,
                defaults={
                    "evento": evento_servos,
                    "ministerio": mref,
                    "funcao": "Serviço",
                    "is_coordenador": is_coord,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            "OK: Casais (nomes realistas, pareados, pagamentos), Servos, Grupos/Ministérios globais e Alocações criados."
        ))
        self.stdout.write(self.style.SUCCESS("Login admin / admin123 (se necessário)."))
