from django.core.management.base import BaseCommand
import random
from datetime import date, timedelta

from inscricoes.models import (
    Paroquia, EventoAcampamento,
    Participante, Inscricao, InscricaoServos
)

class Command(BaseCommand):
    help = "Cria 10 inscrições de servos (completas) e cadastra os ministérios, sem atribuir."

    def handle(self, *args, **kwargs):
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

        # 1) Paróquia
        paroquia, _ = Paroquia.objects.get_or_create(
            nome="PAROQUIA TESTE SERVOS",
            cidade="Tocantinópolis",
            estado="TO",
            responsavel="Pe. João Paulo",
            email="paroquia.servos@example.com",
            telefone="+5563920013103",
        )

        # 2) Evento (servos)
        evento, _ = EventoAcampamento.objects.get_or_create(
            nome="Acampamento Servos 2025",
            tipo="servos",
            data_inicio=date(2025, 11, 20),
            data_fim=date(2025, 11, 23),
            inicio_inscricoes=date(2025, 9, 20),
            fim_inscricoes=date(2025, 11, 15),
            valor_inscricao=0.00,
            paroquia=paroquia,
        )

        # 3) Criar 10 inscrições completas
        nomes_escolhidos = random.sample(NOMES_COMPLETOS, k=NUM_INSCRICOES)
        base_doc = 70000000000  # base para gerar CPFs de teste
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
                evento=evento,
                paroquia=paroquia,
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
                    # sem atribuir ministério
                )
                criados += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ {criados} inscrições de Servos criadas para PAROQUIA TESTE SERVOS (evento: {evento.nome})."
        ))

        # 4) Criar Ministérios (sem atribuir a ninguém)
        try:
            from inscricoes.models import Ministerio  # ajuste se o nome do modelo for diferente
        except Exception:
            Ministerio = None

        if Ministerio:
            count_min = 0
            for n in MINISTERIOS_NOMES:
                _, created = Ministerio.objects.get_or_create(nome=n)
                if created:
                    count_min += 1
            self.stdout.write(self.style.SUCCESS(
                f"✅ Ministérios garantidos: {len(MINISTERIOS_NOMES)} (novos criados: {count_min})."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "⚠️ Modelo 'Ministerio' não encontrado. Ajuste o import se o nome do seu modelo for diferente."
            ))
