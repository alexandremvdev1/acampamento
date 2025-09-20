# scripts/popula_servos.py
import random
from datetime import date, timedelta
from inscricoes.models import (
    Paroquia, EventoAcampamento,
    Participante, Inscricao, InscricaoServos
)

# 🔹 1. Criar Paróquia
paroquia, _ = Paroquia.objects.get_or_create(
    nome="PAROQUIA TESTE SERVOS",
    cidade="Tocantinópolis",
    estado="TO",
    responsavel="Pe. João Paulo",
    email="paroquia.servos@example.com",
    telefone="+5563920013103",
)

# 🔹 2. Criar Evento tipo SERVOS
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

# 🔹 3. Dados de apoio
nomes = [
    "Carlos Silva", "Fernanda Oliveira", "João Santos", "Maria Souza",
    "Paulo Almeida", "Tatiane Costa", "Rogério Lima", "Patrícia Rocha",
    "Eduardo Pereira", "Juliana Ribeiro", "Sérgio Monteiro", "Cláudia Nunes",
]

problemas_exemplo = ["Hipertensão", "Diabetes", "Asma"]
medicamentos_exemplo = ["Insulina", "Anti-hipertensivo", "Inalador"]
alimentos_exemplo = ["Amendoim", "Glúten", "Leite"]
medicamentos_alergia = ["Dipirona", "Penicilina", "Ibuprofeno"]

# Distribuição de cidades (80 servos)
distribuicao_cidades = (
    ["Wanderlândia"] * 30 +
    ["Araguaína"] * 10 +
    ["Palmas"] * 10 +
    ["Tocantinópolis"] * 10 +
    ["Angico"] * 5 +
    ["Darcinópolis"] * 5 +
    ["Aguiarnópolis"] * 5 +
    ["Ananás"] * 5
)

# 🔹 4. Criar participantes e inscrições
for i, cidade in enumerate(distribuicao_cidades, start=1):
    nome = random.choice(nomes) + f" {i}"
    cpf = f"{4000+i:011d}"
    telefone = f"+5563989{i:04d}"
    email = f"servo{i}@example.com"

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
        )
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
            data_nascimento=date.today() - timedelta(days=random.randint(20*365, 50*365)),
            estado_civil=random.choice(["solteiro", "casado"]),
            tamanho_camisa=random.choice(["P", "M", "G", "GG"]),
            problema_saude=problema_saude,
            qual_problema_saude=random.choice(problemas_exemplo) if problema_saude == "sim" else "",
            medicamento_controlado=medicamento_controlado,
            qual_medicamento_controlado=random.choice(medicamentos_exemplo) if medicamento_controlado == "sim" else "",
            alergia_alimento=alergia_alimento,
            qual_alergia_alimento=random.choice(alimentos_exemplo) if alergia_alimento == "sim" else "",
            alergia_medicamento=alergia_medicamento,
            qual_alergia_medicamento=random.choice(medicamentos_alergia) if alergia_medicamento == "sim" else "",
            tipo_sanguineo=random.choice(["A+", "O+", "B+", "AB+", "NS"]),
            batizado=random.choice(["sim", "nao"]),
            crismado=random.choice(["sim", "nao"]),
            dizimista=random.choice(["sim", "nao"]),
        )

print("✅ 80 inscrições de Servos criadas com sucesso para PAROQUIA TESTE SERVOS!")
