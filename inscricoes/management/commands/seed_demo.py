# -*- coding: utf-8 -*-
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from inscricoes.models import (
    Paroquia,
    EventoAcampamento,
    Participante,
    Inscricao,
    InscricaoServos,
    PoliticaReembolso,
    Ministerio,
)

class Command(BaseCommand):
    help = "Seed demo: cria evento principal + servos vinculado, 10 inscrições completas de servos e garante os ministérios (sem atribuir)."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        # -------------------- Configurações --------------------
        NUM_INSCRICOES = 10

        MINISTERIOS_NOMES = [
            "Direção espiritual",
            "Coordenação geral",
            "Condução",
            "Infraestrutura/logistica",
            "Externa",
            "Secretaria",
            "Cozinha",
            "Ordem",
            "Farmácia",
            "Intercessão",
            "Recreação",
            "Manutenção",
            "Padrinhos",
            "Música",
        ]

        NOMES_COMPLETOS = [
            "Alexandre Martins Vieira", "Carlos Henrique Silva", "Fernanda Oliveira Santos",
            "João Paulo Pereira", "Maria Eduarda Souza", "Paulo Roberto Almeida",
            "Tatiane Cristina Costa", "Rogério Augusto Lima", "Patrícia Nogueira Rocha",
            "Eduardo Fernandes Pereira", "Juliana Ribeiro Castro", "Sérgio Monteiro Dias",
            "Cláudia Regina Nunes", "André Luiz Barros", "Camila Azevedo Martins",
            "Leonardo Henrique Carvalho", "Beatriz Figueiredo Alves", "Gabriel Antônio Rocha",
            "Larissa Costa Almeida", "Marcos Vinícius Ferreira", "Isabela Rodrigues Dias",
            "Thiago Almeida Fonseca", "Renata Carvalho Lopes", "Pedro Henrique Ramos",
            "Natália Soares Martins", "Ricardo Gomes da Silva", "Bianca Souza Teixeira",
            "Diego Araújo Fernandes", "Manuela Castro Farias", "Felipe Moura Oliveira",
            "Carolina Mendes Pires", "Rafael Duarte Correia", "Larissa Monteiro Lemos",
            "Victor Hugo Cardoso", "Camila Ribeiro Vasconcelos", "João Vitor Nascimento",
            "Amanda Ferreira Pinto", "Rodrigo Pires de Almeida", "Sofia Nogueira Cunha",
            "Daniel Moreira Campos", "Patrícia Souza Mendes", "Caio Fernando Azevedo",
            "Juliana Monteiro Rocha", "Gustavo Henrique Tavares", "Letícia Carvalho Moura",
            "André Santos Magalhães", "Fernanda Ribeiro Almeida", "Lucas Oliveira Barros",
            "Gabriela Souza Campos", "Henrique Costa Fernandes", "Beatriz Lima Guimarães",
            "Mateus Pereira Duarte", "Mariana Silva Castro", "Cláudio Roberto Mendes",
            "Ana Clara Fernandes", "Felipe Augusto Rocha", "Rafaela Martins Costa",
            "Bruno Henrique Teixeira", "Daniela Moura Almeida", "Rodrigo Alves Ferreira",
            "Bianca Costa Carvalho", "Leonardo Mendes Silva", "Juliana Nogueira Rocha",
            "Eduardo Carvalho Santos", "Carolina Souza Pires", "Gabriel Fernandes Lopes",
            "Vanessa Duarte Monteiro", "Thiago Silva Nogueira", "Natália Ramos Teixeira",
            "Ricardo Oliveira Costa", "Tatiane Gomes Rocha", "André Almeida Souza",
            "Luana Carvalho Mendes", "Felipe Ramos Oliveira", "Larissa Fernandes Costa",
            "Rodrigo Martins Pires", "Beatriz Souza Almeida", "Diego Carvalho Rocha",
            "Camila Ramos Duarte", "Gustavo Oliveira Castro", "Ana Beatriz Nogueira",
            "Marcos Vinícius Rocha", "Juliana Souza Carvalho", "Daniel Ribeiro Almeida",
            "Patrícia Mendes Pires", "Victor Almeida Duarte", "Fernanda Silva Lopes",
            "Lucas Gabriel Rocha", "Camila Fernandes Nogueira", "Eduardo Ramos Teixeira",
            "Sofia Almeida Costa", "Henrique Silva Rocha", "Gabriela Ramos Oliveira"
        ]

        CIDADES = ["Wanderlândia", "Araguaína", "Palmas", "Tocantinópolis", "Angico", "Darcinópolis", "Aguiarnópolis", "Ananás"]

        PROBLEMAS_EXEMPLO = ["Hipertensão", "Diabetes", "Asma"]
        MEDICAMENTOS_EXEMPLO = ["Insulina", "Anti-hipertensivo", "Inalador"]
        ALIMENTOS_ALERGIA = ["Amendoim", "Glúten", "Leite"]
        MEDICAMENTOS_ALERGIA = ["Dipirona", "Penicilina", "Ibuprofeno"]

        # -------------------- Paróquia --------------------
        paroquia, _ = Paroquia.objects.get_or_create(
            nome="PAROQUIA TESTE SERVOS",
            defaults=dict(
                cidade="Tocantinópolis",
                estado="TO",
                responsavel="Pe. João Paulo",
                email="paroquia.servos@example.com",
                telefone="+5563920013103",
                status="ativa",
            )
        )

        # -------------------- Evento Principal (casais) --------------------
        hoje = date.today()
        principal, _ = EventoAcampamento.objects.get_or_create(
            nome="Encontro de Casais DEMO",
            tipo="casais",
            paroquia=paroquia,
            defaults=dict(
                data_inicio=hoje + timedelta(days=30),
                data_fim=hoje + timedelta(days=33),
                inicio_inscricoes=hoje - timedelta(days=5),
                fim_inscricoes=hoje + timedelta(days=25),
                valor_inscricao=Decimal("150.00"),
                permitir_inscricao_servos=True,  # importante para permitir servos
            ),
        )
        # Garante a flag mesmo se o principal já existia
        if not principal.permitir_inscricao_servos:
            principal.permitir_inscricao_servos = True
            principal.save(update_fields=["permitir_inscricao_servos"])

        # Política de reembolso (opcional)
        PoliticaReembolso.objects.get_or_create(
            evento=principal,
            defaults=dict(
                ativo=True,
                permite_reembolso=True,
                prazo_solicitacao_dias=7,
                taxa_administrativa_percent=Decimal("0.00"),
                descricao="Reembolso integral até 7 dias antes do início.",
            )
        )

        # -------------------- Evento de Servos (vinculado) --------------------
        # ⚠️ chavear pelo vínculo para não quebrar a UniqueConstraint
        evento_servos, created_servos = EventoAcampamento.objects.update_or_create(
            tipo="servos",
            evento_relacionado=principal,
            defaults=dict(
                nome="Acampamento Servos 2025",
                paroquia=paroquia,
                data_inicio=principal.data_inicio,
                data_fim=principal.data_fim,
                inicio_inscricoes=principal.inicio_inscricoes,
                fim_inscricoes=principal.fim_inscricoes,
                valor_inscricao=Decimal("0.00"),
            ),
        )

        # Política de reembolso (servos geralmente sem reembolso)
        PoliticaReembolso.objects.get_or_create(
            evento=evento_servos,
            defaults=dict(
                ativo=True,
                permite_reembolso=False,
                prazo_solicitacao_dias=0,
                taxa_administrativa_percent=Decimal("0.00"),
                descricao="Evento de Servos: sem reembolso.",
            )
        )

        # -------------------- 10 inscrições de Servos --------------------
        nomes_escolhidos = random.sample(NOMES_COMPLETOS, k=NUM_INSCRICOES)
        base_doc = 71000000000  # base para CPFs fictícios (11 dígitos)
        criados = 0

        for i in range(NUM_INSCRICOES):
            nome = nomes_escolhidos[i]
            cpf = f"{base_doc + i:011d}"
            telefone = f"+5563989{i:04d}"
            email = f"servo{i+1}@example.com"
            cidade = random.choice(CIDADES)

            participante, _ = Participante.objects.get_or_create(
                cpf=cpf,
                defaults=dict(
                    nome=nome,
                    telefone=telefone,
                    email=email,
                    CEP="77900000",
                    endereco="Rua Principal",
                    numero=str(random.randint(1, 500)),
                    bairro="Centro",
                    cidade=cidade,
                    estado="TO",
                ),
            )

            inscricao, created = Inscricao.objects.get_or_create(
                participante=participante,
                evento=evento_servos,
                defaults=dict(paroquia=paroquia),
            )

            if created:
                problema_saude = random.choice(["sim", "nao"])
                medicamento_controlado = random.choice(["sim", "nao"])
                alergia_alimento = random.choice(["sim", "nao"])
                alergia_medicamento = random.choice(["sim", "nao"])

                InscricaoServos.objects.create(
                    inscricao=inscricao,
                    data_nascimento=date.today() - timedelta(days=random.randint(20 * 365, 50 * 365)),
                    estado_civil=random.choice(["solteiro", "casado"]),
                    tamanho_camisa=random.choice(["P", "M", "G", "GG"]),
                    problema_saude=problema_saude,
                    qual_problema_saude=random.choice(PROBLEMAS_EXEMPLO) if problema_saude == "sim" else "",
                    medicamento_controlado=medicamento_controlado,
                    qual_medicamento_controlado=random.choice(MEDICAMENTOS_EXEMPLO) if medicamento_controlado == "sim" else "",
                    alergia_alimento=alergia_alimento,
                    qual_alergia_alimento=random.choice(ALIMENTOS_ALERGIA) if alergia_alimento == "sim" else "",
                    alergia_medicamento=alergia_medicamento,
                    qual_alergia_medicamento=random.choice(MEDICAMENTOS_ALERGIA) if alergia_medicamento == "sim" else "",
                    tipo_sanguineo=random.choice(["A+", "O+", "B+", "AB+", "NS"]),
                    batizado=random.choice(["sim", "nao"]),
                    crismado=random.choice(["sim", "nao"]),
                    dizimista=random.choice(["sim", "nao"]),
                )
                criados += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ {criados} inscrições de Servos criadas/garantidas (evento: {evento_servos.nome})."
        ))

        # -------------------- Ministérios (sem atribuir) --------------------
        novos_min = 0
        for n in MINISTERIOS_NOMES:
            _, c = Ministerio.objects.get_or_create(
                nome=n,
                defaults=dict(descricao=f"Ministério de {n}")
            )
            if c:
                novos_min += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ Ministérios garantidos: {len(MINISTERIOS_NOMES)} (novos criados: {novos_min})."
        ))

        self.stdout.write(self.style.SUCCESS("Pronto!")) 
