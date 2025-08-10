import uuid
from datetime import date

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.sites.models import Site
from django.core.mail import send_mail, EmailMultiAlternatives
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from cloudinary.models import CloudinaryField


class Paroquia(models.Model):
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('inativa', 'Inativa'),
    ]

    nome = models.CharField(max_length=255)
    cidade = models.CharField(max_length=100)
    estado = models.CharField(max_length=2)
    responsavel = models.CharField(max_length=255)
    email = models.EmailField()
    telefone = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ativa')
    logo = CloudinaryField(null=True,blank=True,verbose_name="Logo da Paróquia")

    def __str__(self):
        return self.nome


class PastoralMovimento(models.Model):
    nome = models.CharField(max_length=200)

    def __str__(self):
        return self.nome


class Participante(models.Model):
    nome      = models.CharField(max_length=150)
    cpf       = models.CharField(max_length=14, unique=True)
    telefone  = models.CharField(max_length=15)
    email     = models.EmailField()
    foto      = CloudinaryField(null=True, blank=True, verbose_name="Foto do Participante")

    CEP       = models.CharField("CEP", max_length=10)
    endereco  = models.CharField("Endereço", max_length=255)
    numero    = models.CharField("Número", max_length=10)
    bairro    = models.CharField("Bairro", max_length=100)
    cidade    = models.CharField("Cidade", max_length=100)
    estado    = models.CharField(
        "Estado", max_length=2,
        choices=[
            ('AC','AC'),('AL','AL'),('AP','AP'),('AM','AM'),('BA','BA'),
            ('CE','CE'),('DF','DF'),('ES','ES'),('GO','GO'),('MA','MA'),
            ('MT','MT'),('MS','MS'),('MG','MG'),('PA','PA'),('PB','PB'),
            ('PR','PR'),('PE','PE'),('PI','PI'),('RJ','RJ'),('RN','RN'),
            ('RS','RS'),('RO','RO'),('RR','RR'),('SC','SC'),('SP','SP'),
            ('SE','SE'),('TO','TO')
        ]
    )

    # Token único para QR Code
    qr_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Token para QR Code"
    )

    def save(self, *args, **kwargs):
        # Garante que novos registros sempre tenham qr_token
        if not self.qr_token:
            self.qr_token = uuid.uuid4()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.cidade} - {self.estado})"


class EventoAcampamento(models.Model):
    TIPO_ACAMPAMENTO = [
        ('senior', 'Acampamento Sênior'),
        ('juvenil', 'Acampamento Juvenil'),
        ('mirim', 'Acampamento Mirim'),
        ('servos', 'Acampamento de Servos'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nome = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=TIPO_ACAMPAMENTO)
    data_inicio = models.DateField()
    data_fim = models.DateField()
    inicio_inscricoes = models.DateField()
    fim_inscricoes = models.DateField()
    valor_inscricao = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00,
        verbose_name="Valor da Inscrição"
    )
    slug = models.SlugField(unique=True, blank=True)
    paroquia = models.ForeignKey("Paroquia", on_delete=models.CASCADE, related_name="eventos")

    banner = CloudinaryField(
    null=True,
    blank=True,
    verbose_name="Banner do Evento"
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            base = f"{self.tipo}-{self.nome}-{self.data_inicio}"
            self.slug = slugify(base)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"

    @property
    def link_inscricao(self):
        # Gera a URL nomeada para a inscrição inicial com o slug do evento
        return reverse('inscricoes:inscricao_inicial', kwargs={'slug': self.slug})

    @property
    def status_inscricao(self):
        hoje = date.today()
        if self.inicio_inscricoes <= hoje <= self.fim_inscricoes:
            return "Inscrições Abertas"
        elif hoje < self.inicio_inscricoes:
            return "Inscrições ainda não iniciadas"
        else:
            return "Inscrições Encerradas"

class Inscricao(models.Model):
    participante = models.ForeignKey('Participante', on_delete=models.CASCADE)
    evento       = models.ForeignKey('EventoAcampamento', on_delete=models.CASCADE)
    paroquia     = models.ForeignKey('Paroquia', on_delete=models.CASCADE, related_name='inscricoes')
    data_inscricao = models.DateTimeField(auto_now_add=True)

    foi_selecionado       = models.BooleanField(default=False)
    pagamento_confirmado  = models.BooleanField(default=False)
    inscricao_concluida   = models.BooleanField(default=False)
    inscricao_enviada     = models.BooleanField(default=False)

    # Responsável 1
    responsavel_1_nome            = models.CharField(max_length=255, blank=True, null=True)
    responsavel_1_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    responsavel_1_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    responsavel_1_ja_e_campista   = models.BooleanField(default=False)

    # Responsável 2
    responsavel_2_nome            = models.CharField(max_length=255, blank=True, null=True)
    responsavel_2_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    responsavel_2_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    responsavel_2_ja_e_campista   = models.BooleanField(default=False)

    # Contato de Emergência
    contato_emergencia_nome            = models.CharField(max_length=255, blank=True, null=True)
    contato_emergencia_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    contato_emergencia_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    contato_emergencia_ja_e_campista   = models.BooleanField(default=False)

    class Meta:
        unique_together = ('participante', 'evento')

    def __str__(self):
        return f"{self.participante.nome} – {self.evento.nome} – {self.paroquia.nome}"

    # ---------------- Helpers ----------------
    @property
    def inscricao_url(self) -> str:
        """
        URL pública para ver a inscrição específica (com botões de pagamento).
        Requer settings.SITE_DOMAIN (ex.: 'https://eismeaqui.app.br') ou Sites Framework.
        """
        relative = reverse('inscricoes:ver_inscricao', args=[self.id])
        base = getattr(settings, "SITE_DOMAIN", "").rstrip("/")
        if not base:
            try:
                current = Site.objects.get_current()
                base = f"https://{current.domain}".rstrip("/")
            except Exception:
                base = ""
        return f"{base}{relative}" if base else relative

    @property
    def portal_participante_url(self) -> str:
        """
        URL do Portal do Participante (tela de CPF).
        Ajuste o nome da rota caso seja diferente de 'inscricoes:portal_participante'.
        """
        relative = reverse('inscricoes:portal_participante')
        base = getattr(settings, "SITE_DOMAIN", "").rstrip("/")
        if not base:
            try:
                current = Site.objects.get_current()
                base = f"https://{current.domain}".rstrip("/")
            except Exception:
                base = ""
        return f"{base}{relative}" if base else relative

    def _site_name(self) -> str:
        site_name = getattr(settings, "SITE_NAME", "") or (getattr(self.paroquia, "nome", "") or "")
        if not site_name:
            try:
                site_name = Site.objects.get_current().domain
            except Exception:
                site_name = "Nossa Equipe"
        return site_name

    def _evento_data_local(self):
        """
        Extrai data e local do evento com fallbacks.
        - data: tenta evento.data_evento, senão evento.data_inicio
        - local: tenta evento.local, senão evento.local_evento
        """
        ev = self.evento
        data = getattr(ev, "data_evento", None) or getattr(ev, "data_inicio", None)
        if data:
            try:
                data_str = timezone.localtime(data).strftime("%d/%m/%Y")
            except Exception:
                try:
                    data_str = data.strftime("%d/%m/%Y")
                except Exception:
                    data_str = str(data)
        else:
            data_str = "A definir"

        local = getattr(ev, "local", None) or getattr(ev, "local_evento", None) or "Local a definir"
        return data_str, local

    # ---------------- E-mails ----------------
    def enviar_email_selecao(self):
        """
        1) Seleção Confirmada – “Você foi selecionado”
        Assunto: 🎉 Parabéns! Você foi selecionado para participar do evento
        (agora com botão para o Portal do Participante)
        """
        if not self.participante.email:
            return

        nome_app = self._site_name()
        data_evento, local_evento = self._evento_data_local()
        portal_url = self.portal_participante_url  # botão principal
        # opcional: link direto da inscrição (fallback)
        link_inscricao = self.inscricao_url

        assunto = "🎉 Parabéns! Você foi selecionado para participar do evento"
        texto = (
            f"Olá {self.participante.nome},\n\n"
            f"Temos uma ótima notícia: você foi selecionado(a) para participar do {self.evento.nome}!\n"
            "Estamos muito felizes em tê-lo(a) conosco nesta experiência especial.\n\n"
            "Detalhes do evento:\n"
            f"📅 Data: {data_evento}\n"
            f"📍 Local: {local_evento}\n\n"
            "Para garantir sua vaga, acesse o Portal do Participante, informe seu CPF e realize o pagamento:\n"
            f"{portal_url}\n\n"
            "(Se preferir, você também pode acessar sua inscrição diretamente:\n"
            f"{link_inscricao})\n\n"
            "Nos vemos no evento!\n"
            f"Abraços,\nEquipe {nome_app}"
        )

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#0f172a">
          <p>Olá <strong>{self.participante.nome}</strong>,</p>
          <p>Temos uma ótima notícia: você foi selecionado(a) para participar do
             <strong>{self.evento.nome}</strong>!</p>
          <p>Estamos muito felizes em tê-lo(a) conosco nesta experiência especial.</p>

          <p><strong>Detalhes do evento:</strong><br>
          📅 Data: {data_evento}<br>
          📍 Local: {local_evento}</p>

          <div style="margin:22px 0;">
            <a href="{portal_url}"
               style="display:inline-block;background:#0ea5e9;color:#fff;
                      padding:12px 20px;border-radius:8px;text-decoration:none;
                      font-weight:700">
              Abrir Portal do Participante
            </a>
          </div>

          <p style="font-size:13px;color:#475569">
            Dica: se preferir, acesse sua inscrição diretamente:
            <a href="{link_inscricao}" style="color:#0ea5e9;text-decoration:none">{link_inscricao}</a>
          </p>

          <p>Nos vemos no evento!<br/>Abraços,<br/>Equipe {nome_app}</p>
        </body></html>
        """

        msg = EmailMultiAlternatives(
            assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email]
        )
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    def enviar_email_pagamento_confirmado(self):
        """
        2) Pagamento Confirmado
        Assunto: ✅ Pagamento confirmado – {{nome_evento}}
        """
        if not self.participante.email:
            return

        nome_app = self._site_name()
        data_evento, local_evento = self._evento_data_local()

        assunto = f"✅ Pagamento confirmado – {self.evento.nome}"
        texto = (
            f"Olá {self.participante.nome},\n\n"
            f"Recebemos a confirmação do seu pagamento para o {self.evento.nome}.\n"
            "Sua inscrição agora está totalmente garantida.\n\n"
            "Resumo da inscrição:\n"
            f"👤 Participante: {self.participante.nome}\n"
            f"📅 Data: {data_evento}\n"
            f"📍 Local: {local_evento}\n\n"
            "Agora é só se preparar e aguardar o grande dia!\n\n"
            f"Até breve,\nEquipe {nome_app}"
        )

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#0f172a">
          <p>Olá <strong>{self.participante.nome}</strong>,</p>
          <p>Recebemos a confirmação do seu pagamento para o
             <strong>{self.evento.nome}</strong>.</p>
          <p>Sua inscrição agora está totalmente garantida.</p>

          <p><strong>Resumo da inscrição:</strong><br>
          👤 Participante: {self.participante.nome}<br>
          📅 Data: {data_evento}<br>
          📍 Local: {local_evento}</p>

          <p>Agora é só se preparar e aguardar o grande dia!</p>
          <p>Até breve,<br/>Equipe {nome_app}</p>
        </body></html>
        """

        msg = EmailMultiAlternatives(
            assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email]
        )
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    def enviar_email_recebida(self):
        """
        3) Inscrição Enviada
        Assunto: 📩 Inscrição recebida – {{nome_evento}}
        (+ aviso do sorteio e e-mail caso seja selecionado)
        """
        if not self.participante.email:
            return

        nome_app = self._site_name()
        data_envio = timezone.localtime(self.data_inscricao).strftime("%d/%m/%Y %H:%M")

        assunto = f"📩 Inscrição recebida – {self.evento.nome}"
        texto = (
            f"Olá {self.participante.nome},\n\n"
            f"Recebemos sua inscrição para o {self.evento.nome}.\n"
            "Nossa equipe vai analisar e, em breve, será realizado o sorteio dos participantes.\n"
            "Você receberá um e-mail caso seja selecionado(a).\n\n"
            "Resumo do envio:\n"
            f"📅 Data do envio: {data_envio}\n"
            f"📍 Evento: {self.evento.nome}\n\n"
            "Fique de olho no seu e-mail para os próximos passos.\n\n"
            f"Atenciosamente,\nEquipe {nome_app}"
        )

        html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#0f172a">
          <p>Olá <strong>{self.participante.nome}</strong>,</p>
          <p>Recebemos sua inscrição para o <strong>{self.evento.nome}</strong>.</p>
          <p>Nossa equipe vai analisar e, em breve, será realizado o sorteio dos participantes.
             Você receberá um e-mail caso seja selecionado(a).</p>

          <p><strong>Resumo do envio:</strong><br>
          📅 Data do envio: {data_envio}<br>
          📍 Evento: {self.evento.nome}</p>

          <p>Fique de olho no seu e-mail para os próximos passos.</p>
          <p>Atenciosamente,<br/>Equipe {nome_app}</p>
        </body></html>
        """

        msg = EmailMultiAlternatives(
            assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email]
        )
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    # ---------------- Disparos automáticos ----------------
    def save(self, *args, **kwargs):
        enviar_selecao   = False
        enviar_pagto_ok  = False
        enviar_recebida  = False

        if self.pk:
            antigo = Inscricao.objects.get(pk=self.pk)

            if not antigo.foi_selecionado and self.foi_selecionado:
                enviar_selecao = True

            if not antigo.pagamento_confirmado and self.pagamento_confirmado:
                enviar_pagto_ok = True
                self.inscricao_concluida = True  # conclui ao confirmar pagamento

            if not antigo.inscricao_enviada and self.inscricao_enviada:
                enviar_recebida = True

        super().save(*args, **kwargs)

        # Dispara após salvar (sem travar o fluxo em caso de erro)
        if enviar_selecao:
            self.enviar_email_selecao()
        if enviar_pagto_ok:
            self.enviar_email_pagamento_confirmado()
        if enviar_recebida:
            self.enviar_email_recebida()


class Pagamento(models.Model):
    class MetodoPagamento(models.TextChoices):
        PIX = 'pix', _('Pix')
        CREDITO = 'credito', _('Cartão de Crédito')
        DEBITO = 'debito', _('Cartão de Débito')
        DINHEIRO = 'dinheiro', _('Dinheiro')

    class StatusPagamento(models.TextChoices):
        PENDENTE = 'pendente', _('Pendente')
        CONFIRMADO = 'confirmado', _('Confirmado')
        CANCELADO = 'cancelado', _('Cancelado')

    inscricao = models.OneToOneField(Inscricao, on_delete=models.CASCADE)
    metodo = models.CharField(
        max_length=20,
        choices=MetodoPagamento.choices,
        default=MetodoPagamento.PIX
    )
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=StatusPagamento.choices,
        default=StatusPagamento.PENDENTE
    )
    data_pagamento = models.DateTimeField(null=True, blank=True)
    transacao_id = models.CharField(max_length=100, blank=True)

    comprovante = models.FileField(
        upload_to='comprovantes_pagamento/',
        null=True,
        blank=True,
        verbose_name='Comprovante de Pagamento'
    )

    def __str__(self):
        return f"Pagamento de {self.inscricao}"


class BaseInscricao(models.Model):
    """Campos comuns às Inscrições (Sênior, Juvenil, Mirim, Servos)."""
    inscricao = models.OneToOneField(
        'Inscricao', on_delete=models.CASCADE, verbose_name="Inscrição"
    )
    data_nascimento = models.DateField(verbose_name="Data de Nascimento")
    altura = models.FloatField(blank=True, null=True, verbose_name="Altura (m)")
    peso = models.FloatField(blank=True, null=True, verbose_name="Peso (kg)")

    SIM_NAO_CHOICES = [
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    batizado = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="É batizado?"
    )

    ESTADO_CIVIL_CHOICES = [
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
    ]
    estado_civil = models.CharField(
        max_length=20,
        choices=ESTADO_CIVIL_CHOICES,
        blank=True,
        null=True,
        verbose_name="Estado Civil"
    )

    casado_na_igreja = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Casado na Igreja?"
    )

    nome_conjuge = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Nome do Cônjuge"
    )
    conjuge_inscrito = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Cônjuge Inscrito?"
    )

    paroquia = models.ForeignKey(
        'Paroquia',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Paróquia"
    )

    pastoral_movimento = models.ForeignKey(
        'PastoralMovimento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Pastoral/Movimento"
    )
    outra_pastoral_movimento = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Outra Pastoral/Movimento"
    )

    dizimista = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Dizimista?"
    )
    crismado = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Crismado?"
    )

    TAMANHO_CAMISA_CHOICES = [
        ('PP', 'PP'), ('P', 'P'), ('M', 'M'),
        ('G', 'G'), ('GG', 'GG'), ('XG', 'XG'), ('XGG', 'XGG'),
    ]
    tamanho_camisa = models.CharField(
        max_length=5,
        choices=TAMANHO_CAMISA_CHOICES,
        blank=True,
        null=True,
        verbose_name="Tamanho da Camisa"
    )

    problema_saude = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Possui algum problema de saúde?"
    )
    qual_problema_saude = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Qual problema de saúde?"
    )

    medicamento_controlado = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Usa algum medicamento controlado?"
    )
    qual_medicamento_controlado = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Qual medicamento controlado?"
    )

    protocolo_administracao = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Protocolo de administração"
    )

    mobilidade_reduzida = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Possui limitações físicas ou mobilidade reduzida?"
    )
    qual_mobilidade_reduzida = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Qual limitação/mobilidade reduzida?"
    )

    # ─── NOVOS CAMPOS DE ALERGIA ─────────────────────────────────────────────
    alergia_alimento = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Possui alergia a algum alimento?"
    )
    qual_alergia_alimento = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Qual alimento causa alergia?"
    )

    alergia_medicamento = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Possui alergia a algum medicamento?"
    )
    qual_alergia_medicamento = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Qual medicamento causa alergia?"
    )
    # ──────────────────────────────────────────────────────────────────────

    TIPO_SANGUINEO_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'),
        ('B-', 'B-'), ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'), ('NS', 'Não sei'),
    ]
    tipo_sanguineo = models.CharField(
        max_length=3,
        choices=TIPO_SANGUINEO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Tipo Sanguíneo"
    )

    indicado_por = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Indicado Por"
    )

    informacoes_extras = models.TextField(
        blank=True,
        null=True,
        verbose_name="Informações extras"
    )

    class Meta:
        abstract = True


class InscricaoSenior(BaseInscricao):
    def __str__(self):
        return f"Inscrição Senior de {self.inscricao.participante.nome}"

class InscricaoJuvenil(BaseInscricao):
    def __str__(self):
        return f"Inscrição Juvenil de {self.inscricao.participante.nome}"

class InscricaoMirim(BaseInscricao):
    def __str__(self):
        return f"Inscrição Mirim de {self.inscricao.participante.nome}"

class InscricaoServos(BaseInscricao):
    def __str__(self):
        return f"Inscrição Servos de {self.inscricao.participante.nome}"

class Contato(models.Model):
    ESCOLHAS_GRAU_PARENTESCO = [
        ('mae', 'Mãe'),
        ('pai', 'Pai'),
        ('irmao', 'Irmão'),
        ('tio', 'Tio'),
        ('tia', 'Tia'),
        ('outro', 'Outro'),
    ]

    inscricao = models.ForeignKey(Inscricao, on_delete=models.CASCADE, related_name='contatos')
    nome = models.CharField(max_length=200)
    telefone = models.CharField(max_length=20)
    grau_parentesco = models.CharField(max_length=20, choices=ESCOLHAS_GRAU_PARENTESCO)
    ja_e_campista = models.BooleanField(default=False)

    def __str__(self):
        return f"Contato de {self.inscricao.participante.nome}: {self.nome}"



TIPOS_USUARIO = [
    ('admin_geral', 'Administrador Geral'),
    ('admin_paroquia', 'Administrador da Paróquia'),
]

class User(AbstractUser):
    tipo_usuario = models.CharField(max_length=20, choices=TIPOS_USUARIO)
    paroquia = models.ForeignKey('Paroquia', null=True, blank=True, on_delete=models.SET_NULL)

    groups = models.ManyToManyField(
        Group,
        related_name='custom_user_set',  # evita conflito com user_set padrão
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
        related_query_name='custom_user',
    )

    user_permissions = models.ManyToManyField(
        Permission,
        related_name='custom_user_set',  # evita conflito
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
        related_query_name='custom_user',
    )

    def is_admin_geral(self):
        return self.tipo_usuario == 'admin_geral'

    def is_admin_paroquia(self):  # Remova models.Model dos parênteses
        return self.tipo_usuario == 'admin_paroquia'

class PoliticaPrivacidade(models.Model):
    texto = models.TextField("Texto da Política de Privacidade")
    imagem_camisa = CloudinaryField(verbose_name="Imagem da Camisa",null=True,blank=True)
    imagem_1 = CloudinaryField(verbose_name="Imagem 1 (opcional)",null=True,blank=True)
    imagem_2 = CloudinaryField(verbose_name="Imagem 2 (opcional)",null=True,blank=True)

    def __str__(self):
        return "Política de Privacidade"
    
class VideoEventoAcampamento(models.Model):
    evento = models.OneToOneField('EventoAcampamento', on_delete=models.CASCADE, related_name='video')
    titulo = models.CharField(max_length=255)
    arquivo = CloudinaryField(resource_type='video',verbose_name="Vídeo do Evento",null=True,blank=True)

    def __str__(self):
        return f"Vídeo de {self.evento.nome}"

    def get_url(self):
        return f"{settings.MEDIA_URL}{self.arquivo.name}"
    
class Conjuge(models.Model):
    SIM_NAO_CHOICES = [
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    inscricao = models.OneToOneField(
        Inscricao,
        on_delete=models.CASCADE,
        related_name='conjuge'
    )
    nome = models.CharField(
        max_length=200,
        blank=True,  # permite valor vazio quando não aplicável
        null=True,
        verbose_name="Nome do Cônjuge"
    )
    conjuge_inscrito = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        default='nao',
        verbose_name="Cônjuge Inscrito?"
    )
    ja_e_campista = models.CharField(
        max_length=3,
        choices=SIM_NAO_CHOICES,
        default='nao',
        verbose_name="Já é Campista?"
    )

    def __str__(self):
        nome = self.nome or '—'
        return f"Cônjuge de {self.inscricao.participante.nome}: {nome}"


class CrachaTemplate(models.Model):
    nome = models.CharField("Nome do Template", max_length=100)
    imagem_fundo = CloudinaryField(verbose_name="Imagem de Fundo",null=True,blank=True)

    def __str__(self):
        return self.nome
    
class MercadoPagoConfig(models.Model):
    paroquia = models.OneToOneField(
        Paroquia,
        on_delete=models.CASCADE,
        related_name="mp_config"
    )
    access_token = models.CharField(
        "Access Token", max_length=255,
        help_text="Token de acesso gerado no painel do Mercado Pago"
    )
    public_key = models.CharField(
        "Public Key", max_length=255,
        help_text="Public Key do Mercado Pago"
    )
    sandbox_mode = models.BooleanField(
        "Sandbox", default=True,
        help_text="Use modo sandbox para testes"
    )

    def __str__(self):
        return f"MP Config para {self.paroquia.nome}"