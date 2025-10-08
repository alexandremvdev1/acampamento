from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
import random
from datetime import date, timedelta
from decimal import Decimal

from inscricoes.models import (
    Paroquia, EventoAcampamento,
    Participante, Inscricao, InscricaoServos, Ministerio
)

class Command(BaseCommand):
    help = "Cria 10 inscrições de servos (completas) e cadastra os ministérios, sem atribuir."

    @transaction.atomic
    def handle(self, *args, **kwargs):
        NUM_INSCRICOES = 10

        MINISTERIOS_NOMES = [
            "Direção espiritual","Coordenação geral","Condução","Infraestrutura/logistica",
            "Externa","Secretaria","Cozinha","Ordem","Farmácia","Intercessão",
            "Recreação","Manutenção","Padrinhos","Música",
        ]

        NOMES_COMPLETOS = [
            "Alexandre Martins Vieira","Carlos Henrique Silva","Fernanda Oliveira Santos",
            "João Paulo Pereira","Maria Eduarda Souza","Paulo Roberto Almeida",
            "Tatiane Cristina Costa","Rogério Augusto Lima","Patrícia Nogueira Rocha",
            "Eduardo Fernandes Pereira","Juliana Ribeiro Castro","Sérgio Monteiro Dias",
            "Cláudia Regina Nunes","André Luiz Barros","Camila Azevedo Martins",
            "Leonardo Henrique Carvalho","Beatriz Figueiredo Alves","Gabriel Antônio Rocha",
            "Larissa Costa Almeida","Marcos Vinícius Ferreira","Isabela Rodrigues Dias",
            "Thiago Almeida Fonseca","Renata Carvalho Lopes","Pedro Henrique Ramos",
            "Natália Soares Martins","Ricardo Gomes da Silva","Bianca Souza Teixeira",
            "Diego Araújo Fernandes","Manuela Castro Farias","Felipe Moura Oliveira",
            "Carolina Mendes Pires","Rafael Duarte Correia","Larissa Monteiro Lemos",
            "Victor Hugo Cardoso","Camila Ribeiro Vasconcelos","João Vitor Nascimento",
            "Amanda Ferreira Pinto","Rodrigo Pires de Almeida","Sofia Nogueira Cunha",
            "Daniel Moreira Campos","Patrícia Souza Mendes","Caio Fernando Azevedo",
            "Juliana Monteiro Rocha","Gustavo Henrique Tavares","Letícia Carvalho Moura",
            "André Santos Magalhães","Fernanda Ribeiro Almeida","Lucas Oliveira Barros",
            "Gabriela Souza Campos","Henrique Costa Fernandes","Beatriz Lima Guimarães",
            "Mateus Pereira Duarte","Mariana Silva Castro","Cláudio Roberto Mendes",
            "Ana Clara Fernandes","Felipe Augusto Rocha","Rafaela Martins Costa",
            "Bruno Henrique Teixeira","Daniela Moura Almeida","Rodrigo Alves Ferreira",
            "Bianca Costa Carvalho","Leonardo Mendes Silva","Juliana Nogueira Rocha",
            "Eduardo Carvalho Santos","Carolina Souza Pires","Gabriel Fernandes Lopes",
            "Vanessa Duarte Monteiro","Thiago Silva Nogueira","Natália Ramos Teixeira",
            "Ricardo Oliveira Costa","Tatiane Gomes Rocha","André Almeida Souza",
            "Luana Carvalho Mendes","Felipe Ramos Oliveira","Larissa Fernandes Costa",
            "Rodrigo Martins Pires","Beatriz Souza Almeida","Diego Carvalho Rocha",
            "Camila Ramos Duarte","Gustavo Oliveira Castro","Ana Beatriz Nogueira",
            "Marcos Vinícius Rocha","Juliana Souza Carvalho","Daniel Ribeiro Almeida",
            "Patrícia Mendes Pires","Victor Almeida Duarte","Fernanda Silva Lopes",
            "Lucas Gabriel Rocha","Camila Fernandes Nogueira","Eduardo Ramos Teixeira",
            "Sofia Almeida Costa","Henrique Silva Rocha","Gabriela Ramos Oliveira"
        ]

        CIDADES = ["Wanderlândia","Araguaína","Palmas","Tocantinópolis","Angico","Darcinópolis","Aguiarnópolis","Ananás"]

        PROBLEMAS_EXEMPLO = ["Hipertensão","Diabetes","Asma"]
        MEDICAMENTOS_EXEMPLO = ["Insulina","Anti-hipertensivo","Inalador"]
        ALIMENTOS_ALERGIA = ["Amendoim","Glúten","Leite"]
        MEDICAMENTOS_ALERGIA = ["Dipirona","Penicilina","Ibuprofeno"]

        # 1) Paróquia
        paroquia, _ = Paroquia.objects.get_or_create(
            nome="PAROQUIA TESTE SERVOS",
            defaults=dict(
                cidade="Tocantinópolis", estado="TO", responsavel="Pe. João Paulo",
                email="paroquia.servos@example.com", telefone="+5563920013103", status="ativa",
            ),
        )

        # 2) Evento principal (≠ servos) com flag que permite inscrições de servos
        di = date(2025, 11, 20)
        df = date(2025, 11, 23)
        inicio_ins = date(2025, 9, 20)
        fim_ins = date(2025, 11, 15)

        principal, _ = EventoAcampamento.objects.get_or_create(
            nome="Encontro de Casais São José 2025",
            tipo="casais",
            paroquia=paroquia,
            defaults=dict(
                data_inicio=di, data_fim=df,
                inicio_inscricoes=inicio_ins, fim_inscricoes=fim_ins,
                valor_inscricao=Decimal("150.00"),
                permitir_inscricao_servos=True,
            ),
        )
        if not principal.permitir_inscricao_servos:
            principal.permitir_inscricao_servos = True
            principal.save(update_fields=["permitir_inscricao_servos"])

        # 3) Evento de SERVOS vinculado ao principal (adota “órfãos” se existirem)
        evento_servos = EventoAcampamento.objects.filter(
            tipo="servos", evento_relacionado=principal
        ).first()

        if not evento_servos:
            # tenta adotar um servos órfão existente (mesma paróquia e, se possível, mesmo nome)
            orfao = (
                EventoAcampamento.objects
                .filter(tipo="servos", evento_relacionado__isnull=True, paroquia=paroquia)
                .order_by("data_inicio")
                .first()
            )
            if orfao:
                orfao.evento_relacionado = principal
                # sincronia opcional de datas/valor para coerência
                orfao.data_inicio = di; orfao.data_fim = df
                orfao.inicio_inscricoes = inicio_ins; orfao.fim_inscricoes = fim_ins
                orfao.valor_inscricao = Decimal("0.00")
                orfao.save(update_fields=[
                    "evento_relacionado","data_inicio","data_fim",
                    "inicio_inscricoes","fim_inscricoes","valor_inscricao"
                ])
                evento_servos = orfao
            else:
                evento_servos = EventoAcampamento.objects.create(
                    nome="Acampamento Servos 2025",
                    tipo="servos",
                    paroquia=paroquia,
                    data_inicio=di, data_fim=df,
                    inicio_inscricoes=inicio_ins, fim_inscricoes=fim_ins,
                    valor_inscricao=Decimal("0.00"),
                    evento_relacionado=principal,
                )

        # segurança extra: falha cedo se ainda não estiver vinculado
        if not evento_servos.evento_relacionado_id:
            raise CommandError("Evento de Servos ainda está sem vínculo com o principal.")

        # 4) 10 inscrições completas
        hoje = date.today()
        nomes_escolhidos = random.sample(NOMES_COMPLETOS, k=NUM_INSCRICOES)
        base_doc = 70000000000
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
                    nome=nome, telefone=telefone, email=email,
                    CEP="77900000", endereco="Rua Principal",
                    numero=str(random.randint(1, 500)), bairro="Centro",
                    cidade=cidade, estado="TO",
                ),
            )

            insc, created = Inscricao.objects.get_or_create(
                participante=participante,
                evento=evento_servos,
                defaults=dict(paroquia=paroquia),
            )

            if created:
                problema_saude = random.choice(["sim","nao"])
                medicamento_controlado = random.choice(["sim","nao"])
                alergia_alimento = random.choice(["sim","nao"])
                alergia_medicamento = random.choice(["sim","nao"])

                InscricaoServos.objects.get_or_create(
                    inscricao=insc,
                    defaults=dict(
                        data_nascimento=hoje - timedelta(days=random.randint(20*365, 50*365)),
                        estado_civil=random.choice(["solteiro","casado"]),
                        tamanho_camisa=random.choice(["P","M","G","GG"]),
                        problema_saude=problema_saude,
                        qual_problema_saude=random.choice(PROBLEMAS_EXEMPLO) if problema_saude == "sim" else "",
                        medicamento_controlado=medicamento_controlado,
                        qual_medicamento_controlado=random.choice(MEDICAMENTOS_EXEMPLO) if medicamento_controlado == "sim" else "",
                        alergia_alimento=alergia_alimento,
                        qual_alergia_alimento=random.choice(ALIMENTOS_ALERGIA) if alergia_alimento == "sim" else "",
                        alergia_medicamento=alergia_medicamento,
                        qual_alergia_medicamento=random.choice(MEDICAMENTOS_ALERGIA) if alergia_medicamento == "sim" else "",
                        tipo_sanguineo=random.choice(["A+","O+","B+","AB+","NS"]),
                        batizado=random.choice(["sim","nao"]),
                        crismado=random.choice(["sim","nao"]),
                        dizimista=random.choice(["sim","nao"]),
                        paroquia=paroquia,
                    ),
                )
                criados += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ {criados} inscrições de Servos criadas para {paroquia.nome} (evento: {evento_servos.nome})."
        ))

        # 5) Catálogo de Ministérios (sem atribuir)
        novos = 0
        for n in MINISTERIOS_NOMES:
            _, c = Ministerio.objects.get_or_create(nome=n, defaults={"descricao": f"Ministério de {n}"})
            if c: novos += 1
        self.stdout.write(self.style.SUCCESS(
            f"✅ Ministérios garantidos: {len(MINISTERIOS_NOMES)} (novos criados: {novos})."
        ))
