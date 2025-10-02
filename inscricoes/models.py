import re
import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import RegexValidator, MinValueValidator, MaxValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.db.utils import IntegrityError

from cloudinary.models import CloudinaryField

# utils de telefone do próprio app
from .utils.phones import normalizar_e164_br, validar_e164_br

# tenta importar o cliente do WhatsApp (sem quebrar em dev)
try:
    from integracoes.whatsapp import (
        send_text,            # texto livre (janela 24h)
        send_template,        # envio cru de template (fallback)
        enviar_inscricao_recebida,
        enviar_selecionado_info,
        enviar_pagamento_recebido,
    )
except Exception:
    send_text = send_template = enviar_inscricao_recebida = enviar_selecionado_info = enviar_pagamento_recebido = None


# ---------------------------------------------------------------------
# Paróquia
# ---------------------------------------------------------------------
class Paroquia(models.Model):
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('inativa', 'Inativa'),
    ]

    nome = models.CharField(max_length=255)  # único obrigatório

    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, blank=True)
    responsavel = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)

    telefone = models.CharField(
        max_length=20,
        blank=True,  # <- opcional
        help_text="Telefone no formato E.164 BR: +55DDDNÚMERO (ex.: +5563920013103)",
        validators=[
            RegexValidator(
                regex=r'^\+55\d{10,11}$',
                message="Formato inválido. Use +55 seguido de 10 ou 11 dígitos (ex.: +5563920013103).",
            )
        ],
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='ativa',
        blank=True,   # opcional no formulário; o default cobre no banco
    )
    logo = CloudinaryField(null=True, blank=True, verbose_name="Logo da Paróquia")

    def __str__(self):
        return self.nome

    def clean(self):
        """Normaliza o telefone digitado para E.164; se falhar, erro amigável."""
        super().clean()
        if self.telefone:
            norm = normalizar_e164_br(self.telefone)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'telefone': "Informe um telefone BR válido. Ex.: +5563920013103"})
            self.telefone = norm

    def save(self, *args, **kwargs):
        # garante normalização também em saves diretos
        if self.telefone:
            norm = normalizar_e164_br(self.telefone)
            if norm:
                self.telefone = norm
        super().save(*args, **kwargs)


class PastoralMovimento(models.Model):
    nome = models.CharField(max_length=200)

    def __str__(self):
        return self.nome


# ---------------------------------------------------------------------
# Participante
# ---------------------------------------------------------------------
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
        choices=[('AC','AC'),('AL','AL'),('AP','AP'),('AM','AM'),('BA','BA'),
                 ('CE','CE'),('DF','DF'),('ES','ES'),('GO','GO'),('MA','MA'),
                 ('MT','MT'),('MS','MS'),('MG','MG'),('PA','PA'),('PB','PB'),
                 ('PR','PR'),('PE','PE'),('PI','PI'),('RJ','RJ'),('RN','RN'),
                 ('RS','RS'),('RO','RO'),('RR','RR'),('SC','SC'),('SP','SP'),
                 ('SE','SE'),('TO','TO')]
    )

    # Token único para QR Code
    qr_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        verbose_name="Token para QR Code"
    )

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = uuid.uuid4()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.cidade} - {self.estado})"


# ---------------------------------------------------------------------
# Evento
# ---------------------------------------------------------------------
class EventoAcampamento(models.Model):
    TIPO_ACAMPAMENTO = [
        ('senior',  'Acampamento Sênior'),
        ('juvenil', 'Acampamento Juvenil'),
        ('mirim',   'Acampamento Mirim'),
        ('servos',  'Acampamento de Servos'),
        # ——— NOVOS TIPOS ———
        ('casais',  'Encontro de Casais'),
        ('evento',  'Evento'),
        ('retiro',  'Retiro'),
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

    banner = CloudinaryField(null=True, blank=True, verbose_name="Banner do Evento")

    # 🔹 Novo campo: flag no PRINCIPAL que libera inscrições do Servos
    permitir_inscricao_servos = models.BooleanField(
        default=False,
        help_text="Se marcado, o evento de Servos vinculado pode receber inscrições."
    )

    # vínculo de evento para Servos
    evento_relacionado = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_servos",
        help_text="Se este for um evento de Servos, vincule ao evento principal em que irão servir."
    )

    def save(self, *args, **kwargs):
        # slug único e resiliente
        if not self.slug:
            base = slugify(f"{self.tipo}-{self.nome}-{self.data_inicio}")
            slug = base
            i = 1
            while EventoAcampamento.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"

    @property
    def is_servos(self) -> bool:
        return (self.tipo or "").lower() == "servos"

    @property
    def principal(self):
        """Se for servos, retorna o evento principal; caso contrário, None."""
        return self.evento_relacionado if self.is_servos else None

    @property
    def servos_evento(self):
        """Retorna o único evento de servos vinculado (se existir)."""
        return self.eventos_servos.filter(tipo="servos").first()

    @property
    def link_inscricao(self):
        return reverse('inscricoes:inscricao_inicial', kwargs={'slug': self.slug})

    @property
    def status_inscricao(self):
        hoje = date.today()
        if self.inicio_inscricoes <= hoje <= self.fim_inscricoes:
            return "Inscrições Abertas"
        elif hoje < self.inicio_inscricoes:
            return "Inscrições ainda não iniciadas"
        return "Inscrições Encerradas"

    class Meta:
        constraints = [
            # Garante no máximo UM evento de servos por principal
            models.UniqueConstraint(
                fields=["evento_relacionado"],
                condition=Q(tipo="servos"),
                name="uniq_servos_por_evento_principal",
            ),
        ]


@receiver(post_save, sender=EventoAcampamento)
def criar_evento_servos_automatico(sender, instance: "EventoAcampamento", created, **kwargs):
    """
    Sempre que um evento PRINCIPAL for criado (qualquer tipo != 'servos'),
    cria automaticamente um evento de 'servos' vinculado, com mesmas datas e paróquia.
    Não habilita inscrições por padrão — depende de 'permitir_inscricao_servos' no principal.
    """
    if not created:
        return
    if (instance.tipo or "").lower() == "servos":
        return

    try:
        # Evita duplicar caso alguém já tenha criado manualmente
        ja_existe = EventoAcampamento.objects.filter(
            tipo="servos",
            evento_relacionado=instance
        ).exists()
        if ja_existe:
            return

        EventoAcampamento.objects.create(
            nome=f"Servos – {instance.nome}",
            tipo="servos",
            data_inicio=instance.data_inicio,
            data_fim=instance.data_fim,
            inicio_inscricoes=instance.inicio_inscricoes,  # ajuste se quiser abrir antes
            fim_inscricoes=instance.fim_inscricoes,
            valor_inscricao=Decimal("0.00"),
            paroquia=instance.paroquia,
            evento_relacionado=instance,
            banner=getattr(instance, "banner", None),
        )
    except IntegrityError:
        # Em caso de corrida, ignore — a constraint já garante unicidade
        pass
    except Exception:
        # Não quebra a criação do principal
        pass


# ---------------------------------------------------------------------
# Inscrição
# ---------------------------------------------------------------------
class Inscricao(models.Model):
    participante = models.ForeignKey('Participante', on_delete=models.CASCADE)
    evento       = models.ForeignKey('EventoAcampamento', on_delete=models.CASCADE)
    paroquia     = models.ForeignKey('Paroquia', on_delete=models.CASCADE, related_name='inscricoes')
    data_inscricao = models.DateTimeField(auto_now_add=True)

    foi_selecionado       = models.BooleanField(default=False)
    pagamento_confirmado  = models.BooleanField(default=False)
    inscricao_concluida   = models.BooleanField(default=False)
    inscricao_enviada     = models.BooleanField(default=False)

    # NOVO: Já é campista?
    ja_e_campista = models.BooleanField(
        default=False,
        verbose_name="Já é campista?"
    )
    tema_acampamento = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Se sim, qual tema do acampamento que participou?"
    )

    # CPF do cônjuge (opcional; usado para localizar e parear depois)
    cpf_conjuge = models.CharField(
        max_length=14, blank=True, null=True,
        help_text="CPF do cônjuge (com ou sem máscara)"
    )

    # Pareamento (bidirecional) com outra inscrição (ex.: casal)
    inscricao_pareada = models.OneToOneField(
        'self',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='pareada_por',
        help_text="Outra inscrição (cônjuge) vinculada"
    )

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
        try:
            relative = reverse('inscricoes:minhas_inscricoes_por_cpf')
        except Exception:
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

    # ---------------- BaseInscricao por tipo ----------------
    def _get_baseinscricao_model(self):
        tipo = (self.evento.tipo or "").strip().lower()
        mapping = {
            'senior':  InscricaoSenior,
            'juvenil': InscricaoJuvenil,
            'mirim':   InscricaoMirim,
            'servos':  InscricaoServos,
            'casais':  InscricaoCasais,   # NOVO
            'evento':  InscricaoEvento,   # NOVO
            'retiro':  InscricaoRetiro,   # NOVO
        }
        return mapping.get(tipo)

    def ensure_base_instance(self):
        Model = self._get_baseinscricao_model()
        if not Model:
            return None
        obj, _created = Model.objects.get_or_create(
            inscricao=self,
            defaults={'paroquia': self.paroquia}
        )
        return obj

    # ---------------- Pareamento ----------------
    @property
    def par(self):
        """Retorna a inscrição pareada (independente do lado)."""
        return self.inscricao_pareada or getattr(self, 'pareada_por', None)

    def clean(self):
        super().clean()

        # Regra de pareamento
        if self.inscricao_pareada:
            if self.inscricao_pareada_id == self.id:
                raise ValidationError({'inscricao_pareada': "Não é possível parear com a própria inscrição."})
            if self.inscricao_pareada.evento_id != self.evento_id:
                raise ValidationError({'inscricao_pareada': "A inscrição pareada deve ser do mesmo evento."})

        # Regra do campista
        if self.ja_e_campista and not self.tema_acampamento:
            raise ValidationError({'tema_acampamento': "Informe o tema do acampamento que participou."})

        # 🔒 Regra: evento de Servos só aceita inscrição se o principal permitir
        if (self.evento.tipo or "").lower() == "servos":
            principal = self.evento.evento_relacionado
            if not principal:
                raise ValidationError({"evento": "Evento de Servos sem vínculo com evento principal."})
            if not principal.permitir_inscricao_servos:
                raise ValidationError("Inscrições de Servos estão desabilitadas para este evento.")

    def set_pareada(self, outra: "Inscricao"):
        """Define o vínculo e espelha nas duas pontas."""
        if not outra:
            self.desparear()
            return
        if outra == self:
            raise ValidationError("Não pode parear consigo mesmo.")
        if outra.evento_id != self.evento_id:
            raise ValidationError("A inscrição pareada deve ser do mesmo evento.")

        with transaction.atomic():
            self.inscricao_pareada = outra
            self.save(update_fields=['inscricao_pareada'])
            if outra.par != self:
                outra.inscricao_pareada = self
                outra.save(update_fields=['inscricao_pareada'])

            # Propaga seleção se evento de casais
            if (self.evento.tipo or '').lower() == 'casais':
                if self.foi_selecionado and not outra.foi_selecionado:
                    outra.foi_selecionado = True
                    outra.save(update_fields=['foi_selecionado'])
                elif outra.foi_selecionado and not self.foi_selecionado:
                    self.foi_selecionado = True
                    self.save(update_fields=['foi_selecionado'])

    def desparear(self):
        """Remove o pareamento nas duas pontas."""
        if self.par:
            outra = self.par
            with transaction.atomic():
                self.inscricao_pareada = None
                self.save(update_fields=['inscricao_pareada'])
                if outra.par == self:
                    outra.inscricao_pareada = None
                    outra.save(update_fields=['inscricao_pareada'])

    # --- util para CPF do cônjuge ---
    def _digits(self, s: str | None) -> str:
        return re.sub(r'\D', '', s or '')

    def _fmt(self, digits: str) -> str:
        return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}" if len(digits) == 11 else digits

    def tentar_vincular_conjuge(self) -> bool:
        """
        Se `cpf_conjuge` estiver preenchido, tenta localizar a inscrição do mesmo evento
        do participante com esse CPF e vincula (bidirecional). Propaga seleção se casais.
        """
        if self.par is not None:
            return False

        d = self._digits(self.cpf_conjuge)
        if len(d) != 11:
            return False

        variantes = {d, self._fmt(d)}

        # 1) Participante do cônjuge
        try:
            conjuge_part = Participante.objects.get(cpf__in=variantes)
        except Participante.DoesNotExist:
            return False

        # 2) Inscrição do mesmo evento
        alvo = Inscricao.objects.filter(
            evento=self.evento,
            participante=conjuge_part,
        ).first()
        if not alvo or alvo.par is not None:
            return False

        # 3) Pareia
        self.set_pareada(alvo)
        return True

    # =============== Pagamento espelhado para casal ===============
    def _propagar_pagamento_para_par(self, confirmado: bool):
        """
        Se evento for CASAIS, sincroniza o status de pagamento com a inscrição pareada
        sem disparar loops/duplicar notificações.
        """
        if (self.evento.tipo or '').lower() != 'casais':
            return
        par = self.par
        if not par:
            return

        # evita update se já está consistente
        if par.pagamento_confirmado == confirmado and par.inscricao_concluida == confirmado:
            return

        with transaction.atomic():
            type(self).objects.filter(pk=par.pk).update(
                pagamento_confirmado=confirmado,
                inscricao_concluida=confirmado,
            )

    # ---------------- E-mails (apenas) ----------------
    def enviar_email_recebida(self):
        """Inscrição recebida (estilo católico/campista)."""
        if not getattr(self.participante, "email", None):
            return

        nome_app = self._site_name()
        data_envio = timezone.localtime(self.data_inscricao).strftime("%d/%m/%Y %H:%M")
        data_evento, _local_evento = self._evento_data_local()

        assunto = f"🙏 Inscrição recebida — {self.evento.nome} ({data_evento})"

        texto = (
            f"Olá {self.participante.nome}!\n\n"
            f"Recebemos sua inscrição para o {self.evento.nome}.\n"
            "Nossa equipe vai analisar e avisaremos os(as) selecionados(as) por e-mail.\n\n"
            "Resumo do envio:\n"
            f"📅 Data do envio: {data_envio}\n"
            f"📍 Evento: {self.evento.nome}\n"
            f"🗓 Data do evento: {data_evento}\n\n"
            "Permaneçamos unidos em oração. Deus abençoe!\n"
            f"Equipe {nome_app}\n"
        )

        html = f"""
        <html><body style="margin:0;font-family:Arial,Helvetica,sans-serif;background:#f7f7f9;color:#222;">
          <div style="max-width:640px;margin:0 auto;">
            <div style="background:#1b2a4a;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0;">
              <h1 style="margin:0;font-size:22px;">Inscrição recebida</h1>
              <p style="margin:6px 0 0;font-size:14px;opacity:.9;">{self.evento.nome}</p>
            </div>
            <div style="background:#fff;padding:22px;border:1px solid #e9e9f1;border-top:none;border-radius:0 0 12px 12px;">
              <p>Olá, <strong>{self.participante.nome}</strong>! ✨</p>
              <p>Recebemos sua <strong>inscrição</strong> para o <strong>{self.evento.nome}</strong>.
                 Em breve avisaremos os(as) selecionados(as).</p>
              <div style="background:#f3f6ff;border-left:4px solid #3c66ff;padding:12px 14px;border-radius:8px;margin:16px 0;">
                <p style="margin:0;"><strong>Resumo do envio</strong></p>
                <p style="margin:6px 0 0;">📅 {data_envio}</p>
              </div>
              <p style="margin:14px 0;">
                Você pode revisar sua inscrição aqui:
                <a href="{self.inscricao_url}" style="color:#1b2a4a;font-weight:bold;">ver minha inscrição</a>.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:18px 0;">
              <p style="font-size:13px;opacity:.8;">
                “Corações ao alto!” — Que o Senhor conduza nossos passos.<br>
                <strong>{nome_app}</strong>
              </p>
            </div>
          </div>
        </body></html>
        """

        msg = EmailMultiAlternatives(assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email])
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    def enviar_email_pagamento_confirmado(self):
        """Pagamento confirmado (estilo católico/campista)."""
        if not getattr(self.participante, "email", None):
            return

        data_evento, local_evento = self._evento_data_local()
        assunto = f"✝️ Pagamento confirmado — {self.evento.nome}"

        texto = (
            f"Olá {self.participante.nome}!\n\n"
            f"Recebemos a confirmação do seu pagamento para o {self.evento.nome}.\n"
            "Sua vaga está garantida. Obrigado por colaborar com a missão!\n\n"
            "Resumo:\n"
            f"👤 Participante: {self.participante.nome}\n"
            f"📅 Data do evento: {data_evento}\n"
            f"📍 Local: {local_evento}\n\n"
            "Prepare o coração, leve sua Bíblia e itens pessoais.\n"
            f"Acompanhe detalhes no Portal do Participante: {self.portal_participante_url}\n\n"
            "Até breve!\n"
            f"Equipe {self._site_name()}\n"
        )

        html = f"""
        <html><body style="margin:0;font-family:Arial,Helvetica,sans-serif;background:#fbfaff;color:#222;">
          <div style="max-width:640px;margin:0 auto;">
            <div style="background:#265d3a;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0;">
              <h1 style="margin:0;font-size:22px;">Pagamento confirmado</h1>
              <p style="margin:6px 0 0;font-size:14px;opacity:.9;">{self.evento.nome}</p>
            </div>
            <div style="background:#fff;padding:22px;border:1px solid #e9efe9;border-top:none;border-radius:0 0 12px 12px;">
              <p>Olá, <strong>{self.participante.nome}</strong>! 💚</p>
              <p>Recebemos seu pagamento. Sua <strong>vaga está garantida</strong>!</p>
              <div style="background:#eef9f1;border-left:4px solid #46a86d;padding:12px 14px;border-radius:8px;margin:16px 0;">
                <p style="margin:0;"><strong>Resumo</strong></p>
                <p style="margin:6px 0 0;">📅 {data_evento} • 📍 {local_evento}</p>
              </div>
              <p>Veja documentos e orientações no Portal do Participante:</p>
              <p style="margin:14px 0;">
                <a href="{self.portal_participante_url}" style="background:#265d3a;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;display:inline-block;">Abrir Portal</a>
              </p>
              <hr style="border:none;border-top:1px solid #e5eee7;margin:18px 0;">
              <p style="font-size:13px;opacity:.8;">“Fazei tudo o que Ele vos disser” (Jo 2,5).</p>
            </div>
          </div>
        </body></html>
        """

        msg = EmailMultiAlternatives(assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email])
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    def enviar_email_selecao(self):
        """Selecionado(a) (estilo católico/campista)."""
        if not getattr(self.participante, "email", None):
            return

        nome_app = self._site_name()
        data_evento, local_evento = self._evento_data_local()

        assunto = f"🎉 Você foi selecionado(a)! — {self.evento.nome}"

        texto = (
            f"Querido(a) {self.participante.nome},\n\n"
            "Com grande alegria, comunicamos que você foi selecionado(a) para participar deste encontro!\n\n"
            "Informações:\n"
            f"🗓 Data: {data_evento}\n"
            f"📍 Local: {local_evento}\n\n"
            f"Confirme sua presença e acompanhe orientações no Portal: {self.portal_participante_url}\n\n"
            "“Vinde a mim, vós todos que estais cansados…” (Mt 11,28).\n"
            f"Conte com nossas orações.\nEquipe {nome_app}\n"
        )

        html = f"""
        <html><body style="margin:0;font-family:Arial,Helvetica,sans-serif;background:#fffdfa;color:#222;">
          <div style="max-width:640px;margin:0 auto;">
            <div style="background:#7a3e1d;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0;background-image:linear-gradient(135deg,#7a3e1d,#a15a31);">
              <h1 style="margin:0;font-size:22px;">Você foi selecionado(a)!</h1>
              <p style="margin:6px 0 0;font-size:14px;opacity:.9;">{self.evento.nome}</p>
            </div>
            <div style="background:#fff;padding:22px;border:1px solid #f0e6df;border-top:none;border-radius:0 0 12px 12px;">
              <p>Querido(a) <strong>{self.participante.nome}</strong>,</p>
              <p>Com grande alegria comunicamos que você foi <strong>selecionado(a)</strong> para participar do evento!</p>
              <div style="background:#fff4e8;border-left:4px solid #f5a25f;padding:12px 14px;border-radius:8px;margin:16px 0;">
                <p style="margin:0;"><strong>Informações importantes</strong></p>
                <p style="margin:6px 0 0;">🗓 {data_evento} • 📍 {local_evento}</p>
              </div>
              <p style="margin:14px 0;">
                <a href="{self.portal_participante_url}" style="background:#7a3e1d;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;display:inline-block;">Confirmar presença / Ver Portal</a>
              </p>
              <hr style="border:none;border-top:1px solid #f2e9e2;margin:18px 0;">
              <p style="font-size:13px;opacity:.85;">
                “Vinde a mim, vós todos que estais cansados…” (Mt 11,28).<br>
                <strong>{nome_app}</strong>
              </p>
            </div>
          </div>
        </body></html>
        """

        msg = EmailMultiAlternatives(assunto, texto, settings.DEFAULT_FROM_EMAIL, [self.participante.email])
        msg.attach_alternative(html, "text/html")
        try:
            msg.send()
        except Exception:
            pass

    # ---------------- Disparos automáticos ----------------
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # 🔒 reforça as validações (inclui regra dos Servos)
        self.full_clean()

        enviar_selecao   = False
        enviar_pagto_ok  = False
        enviar_recebida  = False
        mudou_pagto      = False  # detecta mudança no pagamento

        if self.pk:
            antigo = Inscricao.objects.get(pk=self.pk)

            if not antigo.foi_selecionado and self.foi_selecionado:
                enviar_selecao = True

            mudou_pagto = (antigo.pagamento_confirmado != self.pagamento_confirmado)

            if not antigo.pagamento_confirmado and self.pagamento_confirmado:
                enviar_pagto_ok = True
                self.inscricao_concluida = True  # conclui ao confirmar pagamento
            elif antigo.pagamento_confirmado and not self.pagamento_confirmado:
                # se desfez o pagamento, desfaz conclusão
                self.inscricao_concluida = False

            if not antigo.inscricao_enviada and self.inscricao_enviada:
                enviar_recebida = True

        super().save(*args, **kwargs)

        # Ao criar, garante base correta + tenta parear se já houver cpf_conjuge
        if is_new:
            try:
                self.ensure_base_instance()
            except Exception:
                pass
            try:
                if self.cpf_conjuge:
                    self.tentar_vincular_conjuge()
            except Exception:
                pass

        # Se acabou de ser selecionada e é 'casais', seleciona o par também
        if enviar_selecao and (self.evento.tipo or '').lower() == 'casais':
            par = self.par
            if par and not par.foi_selecionado:
                par.foi_selecionado = True
                par.save()  # dispara notificações do par também

        # Propaga pagamento ao cônjuge se mudou (pago/desfeito) e for CASAIS
        try:
            if (self.evento.tipo or '').lower() == 'casais' and mudou_pagto:
                self._propagar_pagamento_para_par(self.pagamento_confirmado)
        except Exception:
            pass

        # Disparos de e-mail (somente e-mail — WhatsApp removido)
        if enviar_selecao:
            self.enviar_email_selecao()

        if enviar_pagto_ok:
            self.enviar_email_pagamento_confirmado()

        if enviar_recebida:
            self.enviar_email_recebida()


@receiver(post_save, sender=Inscricao)
def _parear_apos_criar(sender, instance: 'Inscricao', created, **kwargs):
    # 1) tentar com o cpf_conjuge desta inscrição
    try:
        if instance.cpf_conjuge and instance.par is None:
            instance.tentar_vincular_conjuge()
    except Exception:
        pass

    # 2) caminho inverso: achar inscrições do mesmo evento que anotaram este CPF como 'cpf_conjuge'
    try:
        meu_cpf_d = re.sub(r'\D', '', getattr(instance.participante, 'cpf', '') or '')
        if len(meu_cpf_d) != 11 or instance.par is not None:
            return
        candidatos = Inscricao.objects.filter(
            evento=instance.evento,
            inscricao_pareada__isnull=True
        ).exclude(pk=instance.pk)
        for c in candidatos:
            alvo_d = re.sub(r'\D', '', c.cpf_conjuge or '')
            if alvo_d == meu_cpf_d:
                c.set_pareada(instance)   # já propaga seleção se for casais
                break
    except Exception:
        pass


class Filho(models.Model):
    inscricao = models.ForeignKey(
        'Inscricao',
        on_delete=models.CASCADE,
        related_name='filhos'
    )
    nome = models.CharField(max_length=255, verbose_name="Nome do Filho")
    idade = models.PositiveIntegerField(verbose_name="Idade")
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefone")
    endereco = models.CharField(max_length=255, blank=True, null=True, verbose_name="Endereço")

    def __str__(self):
        return f"{self.nome} ({self.idade} anos)"


# ---------------------------------------------------------------------
# Pagamento
# ---------------------------------------------------------------------
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
    metodo = models.CharField(max_length=20, choices=MetodoPagamento.choices, default=MetodoPagamento.PIX)
    valor = models.DecimalField(max_digits=8, decimal_places=2)

    # taxas e líquido (já existentes/ajustados)
    fee_mp = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    net_received = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=StatusPagamento.choices, default=StatusPagamento.PENDENTE)
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


# 🔔 NOVO: sincroniza Pagamento → Inscricao e propaga para o cônjuge (casais)
@receiver(post_save, sender=Pagamento)
def _sincronizar_pagamento_inscricao(sender, instance: 'Pagamento', created, **kwargs):
    """
    Ao salvar Pagamento, reflete na Inscricao.pagamento_confirmado e dispara
    a lógica de propagação para o cônjuge (via save() da Inscricao).
    """
    try:
        ins = instance.inscricao
    except Exception:
        return

    status = (instance.status or '').lower()
    deve_marcar = (status == 'confirmado')

    # evita salvar se já está coerente
    if bool(ins.pagamento_confirmado) == deve_marcar and bool(ins.inscricao_concluida) == deve_marcar:
        return

    ins.pagamento_confirmado = deve_marcar
    ins.inscricao_concluida = deve_marcar
    try:
        ins.save()  # save() cuidará de propagar ao cônjuge quando for "casais"
    except Exception:
        pass


# ---------------------------------------------------------------------
# Bases de inscrição por tipo
# ---------------------------------------------------------------------
class BaseInscricao(models.Model):
    """Campos comuns às Inscrições (Sênior, Juvenil, Mirim, Servos, Casais, Evento, Retiro)."""
    inscricao = models.OneToOneField('Inscricao', on_delete=models.CASCADE, verbose_name="Inscrição")
    data_nascimento = models.DateField(verbose_name="Data de Nascimento")
    altura = models.FloatField(blank=True, null=True, verbose_name="Altura (m)")
    peso = models.FloatField(blank=True, null=True, verbose_name="Peso (kg)")

    SIM_NAO_CHOICES = [('sim', 'Sim'), ('nao', 'Não')]

    batizado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="É batizado?")

    ESTADO_CIVIL_CHOICES = [
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
    ]
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True, verbose_name="Estado Civil")

    casado_na_igreja = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Casado na Igreja?")

    tempo_casado_uniao = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Há quanto tempo são casados/estão em união estável?"
    )

    nome_conjuge = models.CharField(max_length=200, blank=True, null=True, verbose_name="Nome do Cônjuge")
    conjuge_inscrito = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Cônjuge Inscrito?")

    paroquia = models.ForeignKey('Paroquia', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Paróquia")

    pastoral_movimento = models.ForeignKey('PastoralMovimento', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Pastoral/Movimento")
    outra_pastoral_movimento = models.CharField(max_length=200, blank=True, null=True, verbose_name="Outra Pastoral/Movimento")

    dizimista = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Dizimista?")
    crismado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Crismado?")

    TAMANHO_CAMISA_CHOICES = [('PP', 'PP'), ('P', 'P'), ('M', 'M'), ('G', 'G'), ('GG', 'GG'), ('XG', 'XG'), ('XGG', 'XGG')]
    tamanho_camisa = models.CharField(max_length=5, choices=TAMANHO_CAMISA_CHOICES, blank=True, null=True, verbose_name="Tamanho da Camisa")

    # ----------------- SAÚDE -----------------
    problema_saude = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui algum problema de saúde?")
    qual_problema_saude = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual problema de saúde?")

    medicamento_controlado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Usa algum medicamento controlado?")
    qual_medicamento_controlado = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual medicamento controlado?")
    protocolo_administracao = models.CharField(max_length=255, blank=True, null=True, verbose_name="Protocolo de administração")

    mobilidade_reduzida = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui limitações físicas ou mobilidade reduzida?")
    qual_mobilidade_reduzida = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual limitação/mobilidade reduzida?")

    # Alergias
    alergia_alimento = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui alergia a algum alimento?")
    qual_alergia_alimento = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual alimento causa alergia?")
    alergia_medicamento = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui alergia a algum medicamento?")
    qual_alergia_medicamento = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual medicamento causa alergia?")

    # NOVOS CAMPOS ESPECÍFICOS
    diabetes = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui Diabetes?")
    pressao_alta = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui Pressão Alta?")

    TIPO_SANGUINEO_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-'), ('NS', 'Não sei')
    ]
    tipo_sanguineo = models.CharField(max_length=3, choices=TIPO_SANGUINEO_CHOICES, blank=True, null=True, verbose_name="Tipo Sanguíneo")

    indicado_por = models.CharField(max_length=200, blank=True, null=True, verbose_name="Indicado Por")
    informacoes_extras = models.TextField(blank=True, null=True, verbose_name="Informações extras")

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


# ——— NOVOS TIPOS ———
class InscricaoCasais(BaseInscricao):
    """
    Inscrição específica para eventos de casais.
    Herda todos os campos de BaseInscricao e adiciona informações extras.
    """
    foto_casal = models.ImageField(
        upload_to="casais/fotos/",
        null=True,
        blank=True,
        verbose_name="Foto do casal"
    )
    tempo_casado_uniao = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Tempo de união"
    )
    casado_na_igreja = models.CharField(
        max_length=10,
        choices=[("sim", "Sim"), ("nao", "Não")],
        null=True,
        blank=True,
        verbose_name="Casado no religioso?"
    )

    def __str__(self):
        return f"Inscrição Casais de {self.inscricao.participante.nome}"


class InscricaoEvento(BaseInscricao):
    def __str__(self):
        return f"Inscrição Evento de {self.inscricao.participante.nome}"


class InscricaoRetiro(BaseInscricao):
    def __str__(self):
        return f"Inscrição Retiro de {self.inscricao.participante.nome}"


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


# ---------------------------------------------------------------------
# Usuário
# ---------------------------------------------------------------------
TIPOS_USUARIO = [
    ('admin_geral', 'Administrador Geral'),
    ('admin_paroquia', 'Administrador da Paróquia'),
]

class User(AbstractUser):
    tipo_usuario = models.CharField(max_length=20, choices=TIPOS_USUARIO)
    paroquia = models.ForeignKey('Paroquia', null=True, blank=True, on_delete=models.SET_NULL)

    groups = models.ManyToManyField(
        Group,
        related_name='custom_user_set',
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
        related_query_name='custom_user',
    )

    user_permissions = models.ManyToManyField(
        Permission,
        related_name='custom_user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
        related_query_name='custom_user',
    )

    def is_admin_geral(self):
        return self.tipo_usuario == 'admin_geral'

    def is_admin_paroquia(self):
        return self.tipo_usuario == 'admin_paroquia'


# ---------------------------------------------------------------------
# Política de Privacidade
# ---------------------------------------------------------------------
class PoliticaPrivacidade(models.Model):
    texto = models.TextField("Texto da Política de Privacidade")
    logo = CloudinaryField(verbose_name="Logo", null=True, blank=True)
    imagem_camisa = CloudinaryField(verbose_name="Imagem da Camisa", null=True, blank=True)
    imagem_1 = CloudinaryField(verbose_name="Imagem 1 (opcional)", null=True, blank=True)
    imagem_2 = CloudinaryField(verbose_name="Imagem 2 (opcional)", null=True, blank=True)

    # NOVO
    imagem_ajuda = CloudinaryField(
        verbose_name="Imagem da Ajuda (botão flutuante)",
        null=True, blank=True
    )

    # Dados do dono do sistema...
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18, blank=True, null=True)
    email_contato = models.EmailField("E-mail de Contato", blank=True, null=True)
    telefone_contato = models.CharField(
        "Telefone de Contato (E.164 BR)",
        max_length=20, blank=True, null=True,
        help_text="Use +55DDDNÚMERO (ex.: +5563920013103)",
        validators=[RegexValidator(
            regex=r'^\+55\d{10,11}$',
            message="Formato inválido. Use +55 seguido de 10 ou 11 dígitos (ex.: +5563920013103).",
        )],
    )
    endereco = models.CharField("Endereço", max_length=255, blank=True, null=True)
    numero = models.CharField("Número", max_length=10, blank=True, null=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True, null=True)
    estado = models.CharField("Estado", max_length=2, blank=True, null=True)

    def __str__(self):
        return "Política de Privacidade"


# ---------------------------------------------------------------------
# Vídeo do Evento (Cloudinary)
# ---------------------------------------------------------------------
class VideoEventoAcampamento(models.Model):
    evento = models.OneToOneField('EventoAcampamento', on_delete=models.CASCADE, related_name='video')
    titulo = models.CharField(max_length=255)
    arquivo = CloudinaryField(resource_type='video', verbose_name="Vídeo do Evento", null=True, blank=True)

    def __str__(self):
        return f"Vídeo de {self.evento.nome}"

    def get_url(self):
        try:
            return self.arquivo.url
        except Exception:
            return ""


# ---------------------------------------------------------------------
# Cônjuge
# ---------------------------------------------------------------------
class Conjuge(models.Model):
    SIM_NAO_CHOICES = [('sim', 'Sim'), ('nao', 'Não')]

    inscricao = models.OneToOneField(
        Inscricao, 
        on_delete=models.CASCADE, 
        related_name='conjuge'
    )
    nome = models.CharField(
        max_length=200, 
        blank=True, 
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
    acampamento = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="De qual acampamento?"
    )

    def __str__(self):
        nome = self.nome or '—'
        return f"Cônjuge de {self.inscricao.participante.nome}: {nome}"


# ---------------------------------------------------------------------
# Template de Crachá
# ---------------------------------------------------------------------
class CrachaTemplate(models.Model):
    nome = models.CharField("Nome do Template", max_length=100)
    imagem_fundo = CloudinaryField(verbose_name="Imagem de Fundo", null=True, blank=True)

    def __str__(self):
        return self.nome


# ---------------------------------------------------------------------
# Mercado Pago Config
# ---------------------------------------------------------------------
class MercadoPagoConfig(models.Model):
    paroquia = models.OneToOneField(Paroquia, on_delete=models.CASCADE, related_name="mp_config")
    access_token = models.CharField("Access Token", max_length=255, help_text="Token de acesso gerado no painel do Mercado Pago")
    public_key = models.CharField("Public Key", max_length=255, help_text="Public Key do Mercado Pago")
    sandbox_mode = models.BooleanField("Sandbox", default=True, help_text="Use modo sandbox para testes")

    def __str__(self):
        return f"MP Config para {self.paroquia.nome}"


# ---------------------------------------------------------------------
# Preferências de Comunicação
# ---------------------------------------------------------------------
class PreferenciasComunicacao(models.Model):
    FONTE_CHOICES = [
        ('form', 'Formulário/Portal'),
        ('admin', 'Admin'),
        ('import', 'Importação'),
    ]

    participante = models.OneToOneField('Participante', on_delete=models.CASCADE, related_name='prefs')
    whatsapp_marketing_opt_in = models.BooleanField(default=False, verbose_name="Aceita marketing no WhatsApp")
    whatsapp_optin_data = models.DateTimeField(null=True, blank=True)
    whatsapp_optin_fonte = models.CharField(max_length=20, choices=FONTE_CHOICES, default='admin')
    whatsapp_optin_prova = models.TextField(blank=True, null=True, help_text="Como foi coletado (ex.: checkbox, IP, data/hora)")
    politica_versao = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"Preferências de {self.participante.nome}"

    def marcar_optin_marketing(self, fonte='admin', prova=None, versao=None):
        self.whatsapp_marketing_opt_in = True
        self.whatsapp_optin_data = timezone.now()
        self.whatsapp_optin_fonte = fonte
        if prova:
            self.whatsapp_optin_prova = prova
        if versao:
            self.politica_versao = versao
        self.save()


@receiver(post_save, sender=Participante)
def criar_prefs(sender, instance, created, **kwargs):
    if created:
        PreferenciasComunicacao.objects.create(participante=instance)


# ---------------------------------------------------------------------
# Política de Reembolso
# ---------------------------------------------------------------------
class PoliticaReembolso(models.Model):
    evento = models.OneToOneField(
        EventoAcampamento,
        on_delete=models.CASCADE,
        related_name='politica_reembolso',
        help_text="Cada evento pode ter (no máximo) uma política de reembolso."
    )
    ativo = models.BooleanField(default=True)
    permite_reembolso = models.BooleanField(
        default=True,
        help_text="Se desmarcado, o evento não aceitará solicitações de reembolso."
    )

    prazo_solicitacao_dias = models.PositiveIntegerField(
        default=7,
        help_text="Dias ANTES do início do evento para solicitar reembolso."
    )
    taxa_administrativa_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Percentual descontado no reembolso (0 a 100)."
    )

    descricao = models.TextField(
        blank=True,
        help_text="Detalhe as regras (ex.: Integral até 7 dias antes; após isso, 70%)."
    )

    contato_email = models.EmailField(blank=True, null=True)
    contato_whatsapp = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="WhatsApp em E.164 (ex.: +5563920013103).",
        validators=[RegexValidator(regex=r'^\+55\d{10,11}$',
                                   message="Use +55 seguido de 10 ou 11 dígitos.")]
    )

    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Política de Reembolso"
        verbose_name_plural = "Políticas de Reembolso"

    def __str__(self):
        return f"Política de Reembolso – {self.evento.nome}"

    def clean(self):
        super().clean()
        if self.contato_whatsapp:
            norm = normalizar_e164_br(self.contato_whatsapp)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'contato_whatsapp': "Informe um telefone BR válido. Ex.: +5563920013103"})
            self.contato_whatsapp = norm

    def save(self, *args, **kwargs):
        if self.contato_whatsapp:
            norm = normalizar_e164_br(self.contato_whatsapp)
            if norm:
                self.contato_whatsapp = norm
        super().save(*args, **kwargs)


class MercadoPagoOwnerConfig(models.Model):
    """
    Credenciais do Mercado Pago do DONO do sistema.
    Usado EXCLUSIVAMENTE para gerar PIX de repasse.
    """
    nome_exibicao = models.CharField(max_length=100, default="Admin do Sistema")
    access_token = models.CharField(max_length=255)  # PROD access token do dono
    notificacao_webhook_url = models.URLField(blank=True, null=True, help_text="Opcional: URL pública do webhook de repasses")
    email_cobranca = models.EmailField(blank=True, null=True, help_text="E-mail que aparecerá como pagador padrão")
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Configuração MP (Dono)"
        verbose_name_plural = "Configurações MP (Dono)"

    def __str__(self):
        return f"MP Dono ({'ativo' if self.ativo else 'inativo'})"


class Repasse(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        CANCELADO = "cancelado", "Cancelado"

    paroquia = models.ForeignKey("inscricoes.Paroquia", on_delete=models.CASCADE, related_name="repasses")
    evento = models.ForeignKey("inscricoes.EventoAcampamento", on_delete=models.CASCADE, related_name="repasses")
    # base = arrecadado confirmado - taxas MP (dos pagamentos das inscrições)
    valor_base = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    taxa_percentual = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"))
    valor_repasse = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)

    # dados do PIX gerado na conta do DONO
    transacao_id = models.CharField(max_length=64, blank=True, null=True)
    qr_code_text = models.TextField(blank=True, null=True)     # copia-e-cola
    qr_code_base64 = models.TextField(blank=True, null=True)   # <img src="data:image/png;base64,...">
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        constraints = [
            models.UniqueConstraint(fields=["paroquia", "evento", "status"], condition=models.Q(status="pendente"), name="uniq_repasse_pendente_por_evento")
        ]

    def __str__(self):
        return f"Repasse {self.paroquia} / {self.evento} — {self.valor_repasse} ({self.status})"


# ---------------------------------------------------------------------
# Mídias do Site (landing / institucional)
# ---------------------------------------------------------------------
class SiteImage(models.Model):
    """
    Repositório central de imagens usadas no site (landing, páginas institucionais).
    Use 'key' para referenciar nas templates.
    """
    CATEGORIA_CHOICES = [
        ("hero", "Hero / Capa"),
        ("screenshot", "Screenshot"),
        ("logo", "Logo/Marca"),
        ("ilustracao", "Ilustração"),
        ("icone", "Ícone"),
        ("banner", "Banner"),
        ("outro", "Outro"),
    ]

    key = models.SlugField("Chave única", max_length=80, unique=True,
                           help_text="Ex.: dashboard, pagamentos, questionario-pronto")
    titulo = models.CharField("Título", max_length=120, blank=True)
    categoria = models.CharField("Categoria", max_length=20, choices=CATEGORIA_CHOICES, default="screenshot")
    imagem = CloudinaryField(verbose_name="Imagem", null=True, blank=True)
    alt_text = models.CharField("Texto alternativo (acessibilidade)", max_length=200, blank=True)
    legenda = models.CharField("Legenda (opcional)", max_length=200, blank=True)
    creditos = models.CharField("Créditos (opcional)", max_length=200, blank=True)
    ativa = models.BooleanField("Ativa?", default=True)
    largura = models.PositiveIntegerField("Largura (px)", null=True, blank=True)
    altura = models.PositiveIntegerField("Altura (px)", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Imagem do Site"
        verbose_name_plural = "Imagens do Site"
        ordering = ["key"]

    def __str__(self):
        return self.key or self.titulo or f"SiteImage #{self.pk}"


# ---------------------------------------------------------------------
# Leads da Landing (Entre em contato)
# ---------------------------------------------------------------------
class LeadLanding(models.Model):
    """
    Leads do formulário 'Entre em contato' (landing).
    """
    nome = models.CharField(max_length=120)
    email = models.EmailField(db_index=True)
    whatsapp = models.CharField(
        max_length=20,
        help_text="WhatsApp em E.164 BR: +55DDDNÚMERO (ex.: +5563920013103)",
        validators=[RegexValidator(
            regex=r'^\+55\d{10,11}$',
            message="Use +55 seguido de 10 ou 11 dígitos (ex.: +5563920013103).",
        )],
    )
    mensagem = models.TextField(blank=True)

    # ATENÇÃO: mantenha o MESMO nome usado no form/template (use 'consent_lgpd').
    consent_lgpd = models.BooleanField(default=False)

    origem = models.CharField(max_length=120, default="landing")

    # Auditoria (úteis p/ analytics básicos)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["email"]),
            models.Index(fields=["origem"]),
        ]

    def __str__(self):
        return f"{self.nome} <{self.email}>"

    @property
    def whatsapp_mascarado(self) -> str:
        """Exibe os 2 últimos dígitos apenas."""
        if not self.whatsapp:
            return ""
        return self.whatsapp[:-2] + "••"

    def clean(self):
        super().clean()
        # Normaliza/valida WhatsApp digitado no site (pode vir sem E.164)
        if self.whatsapp:
            norm = normalizar_e164_br(self.whatsapp)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'whatsapp': "Informe um telefone BR válido. Ex.: +5563920013103"})
            self.whatsapp = norm


@receiver(post_save, sender=LeadLanding)
def _leadlanding_enviar_emails(sender, instance: 'LeadLanding', created, **kwargs):
    if not created:
        return

    # E-mail para a pessoa
    assunto_user = "Recebemos sua mensagem — eismeaqui.app"
    texto_user = (
        f"Olá {instance.nome},\n\n"
        "Recebemos sua mensagem no eismeaqui.app. Em breve retornaremos via e-mail ou WhatsApp.\n\n"
        "Deus abençoe!\nEquipe eismeaqui.app"
    )
    html_user = f"""
    <html><body style="font-family:Arial,sans-serif;color:#0f172a">
      <p>Olá <strong>{instance.nome}</strong>,</p>
      <p>Recebemos sua mensagem no <strong>eismeaqui.app</strong>. Em breve retornaremos via e-mail ou WhatsApp.</p>
      <p>Deus abençoe!<br/>Equipe eismeaqui.app</p>
    </body></html>
    """
    try:
        m1 = EmailMultiAlternatives(assunto_user, texto_user, settings.DEFAULT_FROM_EMAIL, [instance.email])
        m1.attach_alternative(html_user, "text/html")
        m1.send(fail_silently=True)
    except Exception:
        pass

    # E-mail interno (para você/equipe)
    destino_admin = getattr(settings, "SALES_INBOX", settings.DEFAULT_FROM_EMAIL)
    assunto_admin = f"[Landing] Novo contato: {instance.nome}"
    html_admin = f"""
    <html><body style="font-family:Arial,sans-serif;color:#0f172a">
      <h3>Novo contato recebido</h3>
      <p><strong>Nome:</strong> {instance.nome}</p>
      <p><strong>E-mail:</strong> {instance.email}</p>
      <p><strong>WhatsApp:</strong> {instance.whatsapp}</p>
      <p><strong>Mensagem:</strong><br/>{instance.mensagem or '—'}</p>
      <p><small>Origem: {instance.origem} • Data: {timezone.localtime(instance.created_at).strftime('%d/%m/%Y %H:%M')}</small></p>
    </body></html>
    """
    try:
        m2 = EmailMultiAlternatives(assunto_admin, html_admin, settings.DEFAULT_FROM_EMAIL, [destino_admin])
        m2.attach_alternative(html_admin, "text/html")
        m2.send(fail_silently=True)
    except Exception:
        pass


class SiteVisit(models.Model):
    path = models.CharField(max_length=255)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["path"]),
        ]

    def __str__(self):
        return f"{self.ip} {self.path} @ {self.created_at:%Y-%m-%d %H:%M}"


class Comunicado(models.Model):
    paroquia = models.ForeignKey("inscricoes.Paroquia", on_delete=models.CASCADE, related_name="comunicados")
    titulo = models.CharField(max_length=180)
    texto = models.TextField()
    data_publicacao = models.DateField(default=timezone.localdate)
    publicado = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    capa = models.ImageField(upload_to='comunicados/capas/', blank=True, null=True)

    class Meta:
        ordering = ["-data_publicacao", "-created_at"]

    def __str__(self):
        return f"{self.paroquia.nome} • {self.titulo}"


class EventoComunitario(models.Model):
    paroquia = models.ForeignKey("inscricoes.Paroquia", on_delete=models.CASCADE, related_name="eventos_comunidade")
    nome = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, blank=True)  # único dentro da paróquia
    data_inicio = models.DateField()
    data_fim = models.DateField(null=True, blank=True)
    visivel_site = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["data_inicio", "nome"]
        constraints = [
            models.UniqueConstraint(fields=["paroquia", "slug"], name="unique_evento_comunitario_por_paroquia")
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)[:200]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.paroquia.nome} • {self.nome}"


# ---------------------------------------------------------------------
# Grupos e Ministérios (Servos)
# ---------------------------------------------------------------------
class Grupo(models.Model):
    evento = models.ForeignKey("EventoAcampamento", on_delete=models.CASCADE, related_name="grupos")
    nome = models.CharField(max_length=100)
    cor = models.CharField(max_length=20, blank=True, null=True,
                           help_text="Ex.: Amarelo, Vermelho, Azul...")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evento", "nome"], name="uniq_grupo_nome_por_evento"),
        ]

    def clean(self):
        super().clean()
        if not self.nome:
            raise ValidationError({"nome": "Informe o nome do grupo."})

    def __str__(self):
        return f"{self.nome} ({self.evento.nome})"


class Ministerio(models.Model):
    evento = models.ForeignKey("EventoAcampamento", on_delete=models.CASCADE, related_name="ministerios")
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evento", "nome"], name="uniq_ministerio_nome_por_evento"),
        ]

    def clean(self):
        super().clean()
        if (self.evento.tipo or "").lower() != "servos":
            raise ValidationError({"evento": "Ministérios só podem ser cadastrados em eventos do tipo Servos."})

    def __str__(self):
        return f"{self.nome} ({self.evento.nome})"


class AlocacaoMinisterio(models.Model):
    inscricao = models.OneToOneField("Inscricao", on_delete=models.CASCADE, related_name="alocacao_ministerio")
    ministerio = models.ForeignKey("Ministerio", on_delete=models.SET_NULL, null=True, blank=True, related_name="inscricoes")
    funcao = models.CharField(max_length=100, blank=True, null=True, help_text="Ex.: Coordenação, Liturgia, Música...")
    data_alocacao = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.ministerio and (self.inscricao.evento_id != self.ministerio.evento_id):
            raise ValidationError({"ministerio": "Ministério deve pertencer ao mesmo evento da inscrição."})
        # só permitir ministério se o evento da inscrição for Servos
        if (self.inscricao.evento.tipo or "").lower() != "servos":
            raise ValidationError({"inscricao": "Atribuição de ministério só é permitida para eventos de Servos."})

    def __str__(self):
        return f"{self.inscricao.participante.nome} → {self.ministerio.nome if self.ministerio else 'Sem ministério'}"


class AlocacaoGrupo(models.Model):
    inscricao = models.OneToOneField("Inscricao", on_delete=models.CASCADE, related_name="alocacao_grupo")
    grupo = models.ForeignKey("Grupo", on_delete=models.SET_NULL, null=True, blank=True, related_name="inscricoes")
    data_alocacao = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.grupo and (self.inscricao.evento_id != self.grupo.evento_id):
            raise ValidationError({"grupo": "Grupo deve pertencer ao mesmo evento da inscrição."})

    def __str__(self):
        return f"{self.inscricao.participante.nome} → {self.grupo.nome if self.grupo else 'Sem grupo'}"
