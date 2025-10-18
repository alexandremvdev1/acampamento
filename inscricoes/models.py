import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
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
from django.utils.functional import cached_property


from cloudinary.models import CloudinaryField

# utils de telefone do prÃ³prio app
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
# ParÃ³quia
# ---------------------------------------------------------------------
class Paroquia(models.Model):
    STATUS_CHOICES = [
        ('ativa', 'Ativa'),
        ('inativa', 'Inativa'),
    ]

    nome = models.CharField(max_length=255)  # Ãºnico obrigatÃ³rio

    cidade = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, blank=True)
    responsavel = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)

    telefone = models.CharField(
        max_length=20,
        blank=True,  # <- opcional
        help_text="Telefone no formato E.164 BR: +55DDDNÃšMERO (ex.: +5563920013103)",
        validators=[
            RegexValidator(
                regex=r'^\+55\d{10,11}$',
                message="Formato invÃ¡lido. Use +55 seguido de 10 ou 11 dÃ­gitos (ex.: +5563920013103).",
            )
        ],
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='ativa',
        blank=True,   # opcional no formulÃ¡rio; o default cobre no banco
    )

    repasse_percentual = models.DecimalField(
        "Percentual de Repasse ao Dono (%)",
        max_digits=5, decimal_places=2,
        default=Decimal("2.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentual aplicado por padrÃ£o sobre o lÃ­quido arrecadado."
    )
    
    logo = CloudinaryField(null=True, blank=True, verbose_name="Logo da ParÃ³quia")

    def __str__(self):
        return self.nome

    def clean(self):
        """Normaliza o telefone digitado para E.164; se falhar, erro amigÃ¡vel."""
        super().clean()
        if self.telefone:
            norm = normalizar_e164_br(self.telefone)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'telefone': "Informe um telefone BR vÃ¡lido. Ex.: +5563920013103"})
            self.telefone = norm

    def save(self, *args, **kwargs):
        # garante normalizaÃ§Ã£o tambÃ©m em saves diretos
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
    endereco  = models.CharField("EndereÃ§o", max_length=255)
    numero    = models.CharField("NÃºmero", max_length=30)
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

    # Token Ãºnico para QR Code
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
        ('senior',  'Acampamento SÃªnior'),
        ('juvenil', 'Acampamento Juvenil'),
        ('mirim',   'Acampamento Mirim'),
        ('servos',  'Acampamento de Servos'),
        # â€”â€”â€” NOVOS TIPOS â€”â€”â€”
        ('casais',  'Encontro de Casais'),
        ('evento',  'Evento'),
        ('retiro',  'Retiro'),
        ('pagamento', 'Pagamento'),
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
        verbose_name="Valor da InscriÃ§Ã£o"
    )
    slug = models.SlugField(unique=True, blank=True)
    paroquia = models.ForeignKey("Paroquia", on_delete=models.CASCADE, related_name="eventos")

    banner = CloudinaryField(null=True, blank=True, verbose_name="Banner do Evento")

    # Ã°Å¸â€Â¹ Novo campo: flag no PRINCIPAL que libera inscriÃ§Ãµes do Servos
    permitir_inscricao_servos = models.BooleanField(
        default=False,
        help_text="Se marcado, o evento de Servos vinculado pode receber inscriÃ§Ãµes."
    )

    # vÃ­nculo de evento para Servos
    evento_relacionado = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_servos",
        help_text="Se este for um evento de Servos, vincule ao evento principal em que irÃ£o servir."
    )

    def save(self, *args, **kwargs):
        # slug Ãºnico e resiliente
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
        """Se for servos, retorna o evento principal; caso contrÃ¡rio, None."""
        return self.evento_relacionado if self.is_servos else None

    @property
    def servos_evento(self):
        """Retorna o Ãºnico evento de servos vinculado (se existir)."""
        return self.eventos_servos.filter(tipo="servos").first()

    @property
    def link_inscricao(self):
        return reverse('inscricoes:inscricao_inicial', kwargs={'slug': self.slug})

    @property
    def status_inscricao(self):
        hoje = date.today()
        if self.inicio_inscricoes <= hoje <= self.fim_inscricoes:
            return "InscriÃ§Ãµes Abertas"
        elif hoje < self.inicio_inscricoes:
            return "InscriÃ§Ãµes ainda nÃ£o iniciadas"
        return "InscriÃ§Ãµes Encerradas"

    class Meta:
        constraints = [
            # Garante no mÃ¡ximo UM evento de servos por principal
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
    cria automaticamente um evento de 'servos' vinculado, com mesmas datas e parÃ³quia.
    NÃ£o habilita inscriÃ§Ãµes por padrÃ£o â€” depende de 'permitir_inscricao_servos' no principal.
    """
    if not created:
        return
    if (instance.tipo or "").lower() == "servos":
        return

    try:
        # Evita duplicar caso alguÃ©m jÃ¡ tenha criado manualmente
        ja_existe = EventoAcampamento.objects.filter(
            tipo="servos",
            evento_relacionado=instance
        ).exists()
        if ja_existe:
            return

        EventoAcampamento.objects.create(
            nome=f"Servos â€“ {instance.nome}",
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
        # Em caso de corrida, ignore â€” a constraint jÃ¡ garante unicidade
        pass
    except Exception:
        # NÃ£o quebra a criaÃ§Ã£o do principal
        pass


# ---------------------------------------------------------------------
# InscriÃ§Ã£o
# ---------------------------------------------------------------------
class InscricaoStatus(models.TextChoices):
    RASCUNHO        = "draft",         "Rascunho"
    ENVIADA         = "submitted",     "Enviada"
    EM_ANALISE      = "under_review",  "Em anÃ¡lise"
    APROVADA        = "approved",      "Aprovada"            # triagem OK
    LISTA_ESPERA    = "waitlist",      "Lista de espera"
    REJEITADA       = "rejected",      "Rejeitada"

    CONVOCADA       = "selected",      "Selecionada/Convocada"
    PAG_PENDENTE    = "pay_pending",   "Pagamento pendente"
    PAG_CONFIRMADO  = "pay_confirmed", "Pagamento confirmado"

    CANCEL_USUARIO  = "cancel_user",   "Cancelada pelo usuÃ¡rio"
    CANCEL_ADMIN    = "cancel_admin",  "Cancelada pela parÃ³quia"

    REEMB_SOL       = "refund_req",    "Reembolso solicitado"
    REEMB_APROV     = "refund_ok",     "Reembolso aprovado"
    REEMB_NEG       = "refund_den",    "Reembolso negado"


class Inscricao(models.Model):
    # ----- chaves -----
    participante = models.ForeignKey('Participante', on_delete=models.CASCADE)
    evento       = models.ForeignKey('EventoAcampamento', on_delete=models.CASCADE)
    paroquia     = models.ForeignKey('Paroquia', on_delete=models.CASCADE, related_name='inscricoes')
    data_inscricao = models.DateTimeField(auto_now_add=True)

    # ----- status Ãºnico -----
    status = models.CharField(
        max_length=32,
        choices=InscricaoStatus.choices,
        default=InscricaoStatus.RASCUNHO,
        db_index=True,
    )

    # ----- booleans legados (mantidos por espelhamento) -----
    foi_selecionado       = models.BooleanField(default=False)
    pagamento_confirmado  = models.BooleanField(default=False)
    inscricao_concluida   = models.BooleanField(default=False)
    inscricao_enviada     = models.BooleanField(default=False)

    # ----- extras jÃ¡ existentes -----
    ja_e_campista = models.BooleanField(default=False, verbose_name="JÃ¡ Ã© campista?")
    tema_acampamento = models.CharField(max_length=200, blank=True, null=True,
                                        verbose_name="Se sim, qual tema do acampamento que participou?")

    cpf_conjuge = models.CharField(max_length=14, blank=True, null=True,
                                   help_text="CPF do cÃ´njuge (com ou sem mÃ¡scara)")

    inscricao_pareada = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='pareada_por',
        help_text="Outra inscriÃ§Ã£o (cÃ´njuge) vinculada"
    )

    # ResponsÃ¡veis / Contato de EmergÃªncia (mantidos)
    responsavel_1_nome            = models.CharField(max_length=255, blank=True, null=True)
    responsavel_1_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    responsavel_1_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    responsavel_1_ja_e_campista   = models.BooleanField(default=False)

    responsavel_2_nome            = models.CharField(max_length=255, blank=True, null=True)
    responsavel_2_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    responsavel_2_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    responsavel_2_ja_e_campista   = models.BooleanField(default=False)

    contato_emergencia_nome            = models.CharField(max_length=255, blank=True, null=True)
    contato_emergencia_telefone        = models.CharField(max_length=20,  blank=True, null=True)
    contato_emergencia_grau_parentesco = models.CharField(max_length=50,  blank=True, null=True)
    contato_emergencia_ja_e_campista   = models.BooleanField(default=False)

    class Meta:
        unique_together = ('participante', 'evento')

    def __str__(self):
        return f"{self.participante.nome} â€“ {self.evento.nome} â€“ {self.paroquia.nome}"

    # ------------------------------------------------------------
    # URLs Ãºteis
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Leitura rÃ¡pida (derivados do status)
    # ------------------------------------------------------------
    @property
    def is_rejeitada(self):       return self.status == InscricaoStatus.REJEITADA
    @property
    def is_em_analise(self):      return self.status == InscricaoStatus.EM_ANALISE
    @property
    def is_selecionada(self):     return self.status in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}
    @property
    def is_pago(self):            return self.status == InscricaoStatus.PAG_CONFIRMADO
    @property
    def is_cancelada(self):       return self.status in {InscricaoStatus.CANCEL_USER, InscricaoStatus.CANCEL_ADMIN} if hasattr(InscricaoStatus,'CANCEL_USER') else self.status in {InscricaoStatus.CANCEL_USUARIO, InscricaoStatus.CANCEL_ADMIN}

    # ------------------------------------------------------------
    # Mapeamento da base por tipo
    # ------------------------------------------------------------
    def _get_baseinscricao_model(self):
        tipo = (self.evento.tipo or "").strip().lower()
        # importe de forma lazy para evitar ciclos
        from . import inscricaosenior as _s
        from . import inscricaojuvenil as _j
        from . import inscricaomirim as _m
        from . import inscricaoservos as _sv
        from . import inscricaocasais as _c
        from . import inscricaoevento as _e
        from . import inscricaoretiro as _r
        mapping = {
            'senior':  _s.InscricaoSenior,
            'juvenil': _j.InscricaoJuvenil,
            'mirim':   _m.InscricaoMirim,
            'servos':  _sv.InscricaoServos,
            'casais':  _c.InscricaoCasais,
            'evento':  _e.InscricaoEvento,
            'retiro':  _r.InscricaoRetiro,
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

    # ------------------------------------------------------------
    # Pareamento (casais)
    # ------------------------------------------------------------
    @property
    def par(self):
        return self.inscricao_pareada or getattr(self, 'pareada_por', None)

    def set_pareada(self, outra: "Inscricao"):
        if not outra:
            self.desparear()
            return
        if outra == self:
            raise ValidationError("NÃ£o pode parear consigo mesmo.")
        if outra.evento_id != self.evento_id:
            raise ValidationError("A inscriÃ§Ã£o pareada deve ser do mesmo evento.")

        with transaction.atomic():
            self.inscricao_pareada = outra
            self.save(update_fields=['inscricao_pareada'])
            if outra.par != self:
                outra.inscricao_pareada = self
                outra.save(update_fields=['inscricao_pareada'])

            # Sincronias especÃ­ficas de casais
            if self._is_evento_casais():
                # Se um jÃ¡ estÃ¡ pago Ã¢â€ â€™ os dois pagos
                if self.status == InscricaoStatus.PAG_CONFIRMADO and outra.status != InscricaoStatus.PAG_CONFIRMADO:
                    type(self).objects.filter(pk=outra.pk).update(
                        status=InscricaoStatus.PAG_CONFIRMADO,
                        pagamento_confirmado=True,
                        inscricao_concluida=True,
                        foi_selecionado=True,
                    )
                elif outra.status == InscricaoStatus.PAG_CONFIRMADO and self.status != InscricaoStatus.PAG_CONFIRMADO:
                    type(self).objects.filter(pk=self.pk).update(
                        status=InscricaoStatus.PAG_CONFIRMADO,
                        pagamento_confirmado=True,
                        inscricao_concluida=True,
                        foi_selecionado=True,
                    )
                else:
                    # Se um estÃ¡ ao menos selecionado, garante o outro selecionado
                    if self.status in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE} and \
                       outra.status not in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}:
                        type(self).objects.filter(pk=outra.pk).update(
                            status=InscricaoStatus.CONVOCADA,
                            foi_selecionado=True
                        )
                    if outra.status in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE} and \
                       self.status not in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}:
                        type(self).objects.filter(pk=self.pk).update(
                            status=InscricaoStatus.CONVOCADA,
                            foi_selecionado=True
                        )

    def desparear(self):
        if self.par:
            outra = self.par
            with transaction.atomic():
                self.inscricao_pareada = None
                self.save(update_fields=['inscricao_pareada'])
                if outra.par == self:
                    outra.inscricao_pareada = None
                    outra.save(update_fields=['inscricao_pareada'])

    # utils para CPF do cÃ´njuge
    def _digits(self, s: Optional[str]) -> str:
        return re.sub(r'\D', '', s or '')

    def _fmt(self, digits: str) -> str:
        return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}" if len(digits) == 11 else digits

    def tentar_vincular_conjuge(self) -> bool:
        if self.par is not None:
            return False
        d = self._digits(self.cpf_conjuge)
        if len(d) != 11:
            return False
        variantes = {d, self._fmt(d)}
        from . import participante as _p
        try:
            conjuge_part = _p.Participante.objects.get(cpf__in=variantes)
        except _p.Participante.DoesNotExist:
            return False
        alvo = type(self).objects.filter(evento=self.evento, participante=conjuge_part).first()
        if not alvo or alvo.par is not None:
            return False
        self.set_pareada(alvo)
        return True

    # ------------------------------------------------------------
    # Helpers de casal (seleÃ§Ã£o/pagamento)
    # ------------------------------------------------------------
    def _is_evento_casais(self) -> bool:
        return (getattr(self.evento, "tipo", "") or "").lower() == "casais"

    def _propagar_selecao_para_par(self, novo_status: str):
        """
        Em eventos de casais, garante que o par fique ao menos selecionado.
        - Se self foi para PAG_CONFIRMADO: par tambÃ©m vai para PAG_CONFIRMADO.
        - Se self foi para PAG_PENDENTE/CONVOCADA: par vai pelo menos para CONVOCADA.
        Usa update() para evitar recursÃ£o de sinais.
        """
        if not self._is_evento_casais():
            return
        par = self.par
        if not par:
            return

        if novo_status == InscricaoStatus.PAG_CONFIRMADO:
            target = InscricaoStatus.PAG_CONFIRMADO
        elif novo_status in {InscricaoStatus.PAG_PENDENTE, InscricaoStatus.CONVOCADA}:
            # Se o par jÃ¡ estÃ¡ em um destes, nÃ£o baixa
            if par.status in {InscricaoStatus.PAG_CONFIRMADO, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.CONVOCADA}:
                return
            target = InscricaoStatus.CONVOCADA
        else:
            return

        selected_set = {
            InscricaoStatus.CONVOCADA,
            InscricaoStatus.PAG_PENDENTE,
            InscricaoStatus.PAG_CONFIRMADO,
        }

        if target != par.status:
            type(self).objects.filter(pk=par.pk).update(
                status=target,
                foi_selecionado=(target in selected_set),
                pagamento_confirmado=(target == InscricaoStatus.PAG_CONFIRMADO),
                inscricao_concluida=(target == InscricaoStatus.PAG_CONFIRMADO),
            )

    def _propagar_pagamento_para_par(self, confirmado: bool):
        if not self._is_evento_casais():
            return
        par = self.par
        if not par:
            return
        if bool(par.pagamento_confirmado) == confirmado and bool(par.inscricao_concluida) == confirmado and (
            (par.status == InscricaoStatus.PAG_CONFIRMADO) == confirmado
        ):
            return
        with transaction.atomic():
            type(self).objects.filter(pk=par.pk).update(
                status=InscricaoStatus.PAG_CONFIRMADO if confirmado else InscricaoStatus.CONVOCADA,
                pagamento_confirmado=confirmado,
                inscricao_concluida=confirmado,
                foi_selecionado=True,
            )

    # ------------------------------------------------------------
    # ValidaÃ§Ãµes
    # ------------------------------------------------------------
    def clean(self):
        super().clean()
        # pareamento: mesmo evento
        if self.inscricao_pareada:
            if self.inscricao_pareada_id == self.id:
                raise ValidationError({'inscricao_pareada': "NÃ£o Ã© possÃ­vel parear com a prÃ³pria inscriÃ§Ã£o."})
            if self.inscricao_pareada.evento_id != self.evento_id:
                raise ValidationError({'inscricao_pareada': "A inscriÃ§Ã£o pareada deve ser do mesmo evento."})

        # campista: precisa do tema
        if self.ja_e_campista and not self.tema_acampamento:
            raise ValidationError({'tema_acampamento': "Informe o tema do acampamento que participou."})

        # evento de Servos precisa ter principal permitindo
        if (self.evento.tipo or "").lower() == "servos":
            principal = getattr(self.evento, "evento_relacionado", None)
            if not principal:
                raise ValidationError({"evento": "Evento de Servos sem vÃ­nculo com evento principal."})
            if not getattr(principal, "permitir_inscricao_servos", False):
                raise ValidationError("InscriÃ§Ãµes de Servos estÃ£o desabilitadas para este evento.")

    # ------------------------------------------------------------
    # Disparos (stubs â€” substitua pelas suas implementaÃ§Ãµes)
    # ------------------------------------------------------------
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

    def _telefone_e164(self) -> Optional[str]:
        try:
            tel = getattr(self.participante, "telefone", None)
            return normalizar_e164_br(tel) if tel else None
        except Exception:
            return None

    # â€”â€” stubs (implemente conforme o seu projeto) â€”â€”
    def enviar_email_selecao(self): pass
    def enviar_email_pagamento_confirmado(self): pass
    def enviar_email_recebida(self): pass
    def enviar_whatsapp_selecao(self): pass
    def enviar_whatsapp_pagamento_confirmado(self): pass
    def enviar_whatsapp_recebida(self): pass

    # ------------------------------------------------------------
    # Espelhamento booleans (retrocompat)
    # ------------------------------------------------------------
    def _espelhar_booleans(self):
        st = self.status
        self.inscricao_enviada    = st not in {InscricaoStatus.RASCUNHO}
        self.foi_selecionado      = st in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE, InscricaoStatus.PAG_CONFIRMADO}
        self.pagamento_confirmado = st == InscricaoStatus.PAG_CONFIRMADO
        self.inscricao_concluida  = st == InscricaoStatus.PAG_CONFIRMADO

    # ------------------------------------------------------------
    # MÃ¡quina de estados e transiÃ§Ãµes
    # ------------------------------------------------------------
    _NEXT = {
        InscricaoStatus.RASCUNHO:       {InscricaoStatus.ENVIADA, InscricaoStatus.CANCEL_USUARIO},
        InscricaoStatus.ENVIADA:        {InscricaoStatus.EM_ANALISE, InscricaoStatus.CANCEL_USUARIO},
        InscricaoStatus.EM_ANALISE:     {InscricaoStatus.APROVADA, InscricaoStatus.REJEITADA, InscricaoStatus.LISTA_ESPERA, InscricaoStatus.CANCEL_ADMIN},
        InscricaoStatus.APROVADA:       {InscricaoStatus.CONVOCADA, InscricaoStatus.LISTA_ESPERA, InscricaoStatus.CANCEL_ADMIN},
        InscricaoStatus.LISTA_ESPERA:   {InscricaoStatus.CONVOCADA, InscricaoStatus.CANCEL_ADMIN, InscricaoStatus.REJEITADA},
        InscricaoStatus.CONVOCADA:      {InscricaoStatus.PAG_PENDENTE, InscricaoStatus.CANCEL_ADMIN},
        InscricaoStatus.PAG_PENDENTE:   {InscricaoStatus.PAG_CONFIRMADO, InscricaoStatus.CANCEL_ADMIN},
        InscricaoStatus.PAG_CONFIRMADO: {InscricaoStatus.REEMB_SOL, InscricaoStatus.CANCEL_ADMIN},
        InscricaoStatus.REEMB_SOL:      {InscricaoStatus.REEMB_APROV, InscricaoStatus.REEMB_NEG},
    }

    def mudar_status(self, novo_status: str, *, motivo: Optional[str] = None, por_usuario=None) -> bool:
        """Aplica transiÃ§Ã£o validada e dispara eventos usuais + propagaÃ§Ã£o para par."""
        if novo_status == self.status:
            return False
        permitidos = self._NEXT.get(self.status, set())
        if novo_status not in permitidos:
            raise ValidationError(
                f"TransiÃ§Ã£o invÃ¡lida: {self.get_status_display()} Ã¢â€ â€™ "
                f"{dict(InscricaoStatus.choices).get(novo_status, novo_status)}"
            )
        with transaction.atomic():
            antigo = self.status
            self.status = novo_status
            self._espelhar_booleans()
            super().save(update_fields=["status","foi_selecionado","pagamento_confirmado","inscricao_concluida","inscricao_enviada"])

            # logs (opcional)
            try:
                from .models import LogAcao  # ajuste se existir
                LogAcao.objects.create(
                    tipo="status_change",
                    usuario=por_usuario,
                    inscricao=self,
                    detalhes={"de": antigo, "para": novo_status, "motivo": motivo},
                )
            except Exception:
                pass

            # disparos usuais
            if antigo != InscricaoStatus.CONVOCADA and novo_status in {InscricaoStatus.CONVOCADA, InscricaoStatus.PAG_PENDENTE}:
                self.enviar_email_selecao()
                self.enviar_whatsapp_selecao()

            if novo_status == InscricaoStatus.PAG_CONFIRMADO:
                self.enviar_email_pagamento_confirmado()
                self.enviar_whatsapp_pagamento_confirmado()
                # casais: propagar pgto
                try:
                    self._propagar_pagamento_para_par(True)
                except Exception:
                    pass

            if antigo == InscricaoStatus.RASCUNHO and novo_status == InscricaoStatus.ENVIADA:
                self.enviar_email_recebida()
                self.enviar_whatsapp_recebida()

            # Propagar seleÃ§Ã£o/pagamento para o par (casais)
            try:
                self._propagar_selecao_para_par(novo_status)
            except Exception:
                pass

        return True

    # ------------------------------------------------------------
    # SAVE: reforÃ§a validaÃ§Ãµes + mantÃ©m comportamento legado
    # ------------------------------------------------------------
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        self.full_clean()

        # comportamento legado: se setaram booleans diretamente,
        # convertemos para o status correspondente.
        status_alvo = None
        if self.pagamento_confirmado:
            status_alvo = InscricaoStatus.PAG_CONFIRMADO
        elif self.foi_selecionado and not self.pagamento_confirmado:
            status_alvo = InscricaoStatus.PAG_PENDENTE
        elif self.inscricao_enviada and self.status == InscricaoStatus.RASCUNHO:
            status_alvo = InscricaoStatus.ENVIADA

        if status_alvo and status_alvo != self.status:
            try:
                self.mudar_status(status_alvo, motivo="Autoajuste booleansÃ¢â€ â€™status")
                return  # mudar_status jÃ¡ salvou
            except ValidationError:
                self.status = status_alvo

        # espelha booleans corretos do status atual
        self._espelhar_booleans()

        super().save(*args, **kwargs)

        # pÃ³s-criaÃ§Ã£o: garante base + tenta parear por CPF do cÃ´njuge
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

class Filho(models.Model):
    inscricao = models.ForeignKey(
        'Inscricao',
        on_delete=models.CASCADE,
        related_name='filhos'
    )
    nome = models.CharField(max_length=255, verbose_name="Nome do Filho")
    idade = models.PositiveIntegerField(verbose_name="Idade")
    telefone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefone")
    endereco = models.CharField(max_length=255, blank=True, null=True, verbose_name="EndereÃ§o")

    def __str__(self):
        return f"{self.nome} ({self.idade} anos)"


# ---------------------------------------------------------------------
# Pagamento
# ---------------------------------------------------------------------
class Pagamento(models.Model):
    class MetodoPagamento(models.TextChoices):
        PIX = 'pix', _('Pix')
        CREDITO = 'credito', _('CartÃ£o de CrÃ©dito')
        DEBITO = 'debito', _('CartÃ£o de DÃ©bito')
        DINHEIRO = 'dinheiro', _('Dinheiro')

    class StatusPagamento(models.TextChoices):
        PENDENTE = 'pendente', _('Pendente')
        CONFIRMADO = 'confirmado', _('Confirmado')
        CANCELADO = 'cancelado', _('Cancelado')

    inscricao = models.OneToOneField(Inscricao, on_delete=models.CASCADE)
    metodo = models.CharField(max_length=20, choices=MetodoPagamento.choices, default=MetodoPagamento.PIX)
    valor = models.DecimalField(max_digits=8, decimal_places=2)

    # taxas e lÃ­quido (jÃ¡ existentes/ajustados)
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


# Ã°Å¸â€â€ NOVO: sincroniza Pagamento Ã¢â€ â€™ Inscricao e propaga para o cÃ´njuge (casais)
@receiver(post_save, sender=Pagamento)
def _sincronizar_pagamento_inscricao(sender, instance: 'Pagamento', created, **kwargs):
    """
    Ao salvar Pagamento, reflete na Inscricao.pagamento_confirmado e dispara
    a lÃ³gica de propagaÃ§Ã£o para o cÃ´njuge (via save() da Inscricao).
    """
    try:
        ins = instance.inscricao
    except Exception:
        return

    status = (instance.status or '').lower()
    deve_marcar = (status == 'confirmado')

    # evita salvar se jÃ¡ estÃ¡ coerente
    if bool(ins.pagamento_confirmado) == deve_marcar and bool(ins.inscricao_concluida) == deve_marcar:
        return

    ins.pagamento_confirmado = deve_marcar
    ins.inscricao_concluida = deve_marcar
    try:
        ins.save()  # save() cuidarÃ¡ de propagar ao cÃ´njuge quando for "casais"
    except Exception:
        pass


# ---------------------------------------------------------------------
# Bases de inscriÃ§Ã£o por tipo
# ---------------------------------------------------------------------
class BaseInscricao(models.Model):
    """Campos comuns ÃƒÂ s InscriÃ§Ãµes (SÃªnior, Juvenil, Mirim, Servos, Casais, Evento, Retiro)."""
    inscricao = models.OneToOneField('Inscricao', on_delete=models.CASCADE, verbose_name="InscriÃ§Ã£o")
    data_nascimento = models.DateField(verbose_name="Data de Nascimento")
    altura = models.FloatField(blank=True, null=True, verbose_name="Altura (m)")
    peso = models.FloatField(blank=True, null=True, verbose_name="Peso (kg)")

    SIM_NAO_CHOICES = [('sim', 'Sim'), ('nao', 'NÃ£o')]

    batizado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Ã‰ batizado?")

    ESTADO_CIVIL_CHOICES = [
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'ViÃºvo(a)'),
        ('uniao_estavel', 'UniÃ£o EstÃ¡vel'),
    ]
    estado_civil = models.CharField(max_length=20, choices=ESTADO_CIVIL_CHOICES, blank=True, null=True, verbose_name="Estado Civil")

    casado_na_igreja = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Casado na Igreja?")

    tempo_casado_uniao = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="HÃ¡ quanto tempo sÃ£o casados/estÃ£o em uniÃ£o estÃ¡vel?"
    )

    nome_conjuge = models.CharField(max_length=200, blank=True, null=True, verbose_name="Nome do CÃ´njuge")
    conjuge_inscrito = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="CÃ´njuge Inscrito?")

    paroquia = models.ForeignKey('Paroquia', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ParÃ³quia")
    outra_paroquia = models.CharField(
        "Outra parÃ³quia (texto livre)",
        max_length=120,
        blank=True,
        help_text="Preencha se nÃ£o encontrou sua parÃ³quia na lista."
    )
    pastoral_movimento = models.ForeignKey('PastoralMovimento', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Pastoral/Movimento")
    outra_pastoral_movimento = models.CharField(max_length=200, blank=True, null=True, verbose_name="Outra Pastoral/Movimento")

    dizimista = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Dizimista?")
    crismado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Crismado?")

    TAMANHO_CAMISA_CHOICES = [('PP', 'PP'), ('P', 'P'), ('M', 'M'), ('G', 'G'), ('GG', 'GG'), ('XG', 'XG'), ('XGG', 'XGG')]
    tamanho_camisa = models.CharField(max_length=5, choices=TAMANHO_CAMISA_CHOICES, blank=True, null=True, verbose_name="Tamanho da Camisa")

    # ----------------- SAÃšDE -----------------
    problema_saude = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui algum problema de saÃºde?")
    qual_problema_saude = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual problema de saÃºde?")

    medicamento_controlado = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Usa algum medicamento controlado?")
    qual_medicamento_controlado = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual medicamento controlado?")
    protocolo_administracao = models.CharField(max_length=255, blank=True, null=True, verbose_name="Protocolo de administraÃ§Ã£o")

    mobilidade_reduzida = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui limitaÃ§Ãµes fÃ­sicas ou mobilidade reduzida?")
    qual_mobilidade_reduzida = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual limitaÃ§Ã£o/mobilidade reduzida?")

    # Alergias
    alergia_alimento = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui alergia a algum alimento?")
    qual_alergia_alimento = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual alimento causa alergia?")
    alergia_medicamento = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui alergia a algum medicamento?")
    qual_alergia_medicamento = models.CharField(max_length=255, blank=True, null=True, verbose_name="Qual medicamento causa alergia?")

    # NOVOS CAMPOS ESPECÃƒÂFICOS
    diabetes = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui Diabetes?")
    pressao_alta = models.CharField(max_length=3, choices=SIM_NAO_CHOICES, blank=True, null=True, verbose_name="Possui PressÃ£o Alta?")

    TIPO_SANGUINEO_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-'), ('NS', 'NÃ£o sei')
    ]
    tipo_sanguineo = models.CharField(max_length=3, choices=TIPO_SANGUINEO_CHOICES, blank=True, null=True, verbose_name="Tipo SanguÃ­neo")

    indicado_por = models.CharField(max_length=200, blank=True, null=True, verbose_name="Indicado Por")
    informacoes_extras = models.TextField(blank=True, null=True, verbose_name="InformaÃ§Ãµes extras")

    class Meta:
        abstract = True


class InscricaoSenior(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Senior de {self.inscricao.participante.nome}"


class InscricaoJuvenil(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Juvenil de {self.inscricao.participante.nome}"


class InscricaoMirim(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Mirim de {self.inscricao.participante.nome}"


class InscricaoServos(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Servos de {self.inscricao.participante.nome}"


# â€”â€”â€” NOVOS TIPOS â€”â€”â€”
class InscricaoCasais(BaseInscricao):
    """
    InscriÃ§Ã£o especÃ­fica para eventos de casais.
    Herda todos os campos de BaseInscricao e adiciona informaÃ§Ãµes extras.
    """
    foto_casal = models.ImageField(upload_to="casais/fotos/", blank=True, null=True)

    tempo_casado_uniao = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Tempo de uniÃ£o"
    )
    casado_na_igreja = models.CharField(
        max_length=10,
        choices=[("sim", "Sim"), ("nao", "NÃ£o")],
        null=True,
        blank=True,
        verbose_name="Casado no religioso?"
    )

    def __str__(self):
        return f"InscriÃ§Ã£o Casais de {self.inscricao.participante.nome}"


class InscricaoEvento(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Evento de {self.inscricao.participante.nome}"


class InscricaoRetiro(BaseInscricao):
    def __str__(self):
        return f"InscriÃ§Ã£o Retiro de {self.inscricao.participante.nome}"


class Contato(models.Model):
    ESCOLHAS_GRAU_PARENTESCO = [
        ('mae', 'MÃ£e'),
        ('pai', 'Pai'),
        ('irmao', 'IrmÃ£o'),
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
# UsuÃ¡rio
# ---------------------------------------------------------------------
TIPOS_USUARIO = [
    ('admin_geral', 'Administrador Geral'),
    ('admin_paroquia', 'Administrador da ParÃ³quia'),
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
# PolÃ­tica de Privacidade
# ---------------------------------------------------------------------
class PoliticaPrivacidade(models.Model):
    texto = models.TextField("Texto da PolÃ­tica de Privacidade")
    logo = CloudinaryField(verbose_name="Logo", null=True, blank=True)
    imagem_camisa = CloudinaryField(verbose_name="Imagem da Camisa", null=True, blank=True)
    imagem_1 = CloudinaryField(verbose_name="Imagem 1 (opcional)", null=True, blank=True)
    imagem_2 = CloudinaryField(verbose_name="Imagem 2 (opcional)", null=True, blank=True)

    # NOVO
    imagem_ajuda = CloudinaryField(
        verbose_name="Imagem da Ajuda (botÃ£o flutuante)",
        null=True, blank=True
    )
    
    imagem_pagto = CloudinaryField(
        verbose_name="Imagem do Pagamento (PIX / instruÃ§Ãµes)",
        null=True, blank=True
    )

    imagem_insc = CloudinaryField(
        verbose_name="Imagem da InscriÃ§Ã£o",
        null=True, blank=True,
        help_text="Imagem exibida nas telas de inscriÃ§Ã£o (opcional)."
    )

    # Dados do dono do sistema...
    cpf_cnpj = models.CharField("CPF/CNPJ", max_length=18, blank=True, null=True)
    email_contato = models.EmailField("E-mail de Contato", blank=True, null=True)
    telefone_contato = models.CharField(
        "Telefone de Contato (E.164 BR)",
        max_length=20, blank=True, null=True,
        help_text="Use +55DDDNÃšMERO (ex.: +5563920013103)",
        validators=[RegexValidator(
            regex=r'^\+55\d{10,11}$',
            message="Formato invÃ¡lido. Use +55 seguido de 10 ou 11 dÃ­gitos (ex.: +5563920013103).",
        )],
    )
    endereco = models.CharField("EndereÃ§o", max_length=255, blank=True, null=True)
    numero = models.CharField("NÃºmero", max_length=10, blank=True, null=True)
    bairro = models.CharField("Bairro", max_length=100, blank=True, null=True)
    estado = models.CharField("Estado", max_length=2, blank=True, null=True)

    def __str__(self):
        return "PolÃ­tica de Privacidade"


# ---------------------------------------------------------------------
# VÃ­deo do Evento (Cloudinary)
# ---------------------------------------------------------------------
class VideoEventoAcampamento(models.Model):
    evento = models.OneToOneField('EventoAcampamento', on_delete=models.CASCADE, related_name='video')
    titulo = models.CharField(max_length=255)
    arquivo = CloudinaryField(resource_type='video', verbose_name="VÃ­deo do Evento", null=True, blank=True)

    def __str__(self):
        return f"VÃ­deo de {self.evento.nome}"

    def get_url(self):
        try:
            return self.arquivo.url
        except Exception:
            return ""


# ---------------------------------------------------------------------
# CÃ´njuge
# ---------------------------------------------------------------------
class Conjuge(models.Model):
    SIM_NAO_CHOICES = [('sim', 'Sim'), ('nao', 'NÃ£o')]

    inscricao = models.OneToOneField(
        Inscricao, 
        on_delete=models.CASCADE, 
        related_name='conjuge'
    )
    nome = models.CharField(
        max_length=200, 
        blank=True, 
        null=True, 
        verbose_name="Nome do CÃ´njuge"
    )
    conjuge_inscrito = models.CharField(
        max_length=3, 
        choices=SIM_NAO_CHOICES, 
        default='nao', 
        verbose_name="CÃ´njuge Inscrito?"
    )
    ja_e_campista = models.CharField(
        max_length=3, 
        choices=SIM_NAO_CHOICES, 
        default='nao', 
        verbose_name="JÃ¡ Ã© Campista?"
    )
    acampamento = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="De qual acampamento?"
    )

    def __str__(self):
        nome = self.nome or 'â€”'
        return f"CÃ´njuge de {self.inscricao.participante.nome}: {nome}"


# ---------------------------------------------------------------------
# Template de CrachÃ¡
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
    access_token = models.CharField("Access Token", max_length=255)
    public_key   = models.CharField("Public Key", max_length=255)
    sandbox_mode = models.BooleanField("Sandbox", default=True)

    # >>> NOVOS CAMPOS (taxas)
    taxa_pix_percent      = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
                           validators=[MinValueValidator(0), MaxValueValidator(100)],
                           help_text="Percentual sobre o valor do PIX (ex.: 0.99 para 0,99%)")
    taxa_pix_fixa         = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"),
                           help_text="Valor fixo por transaÃ§Ã£o PIX")
    taxa_credito_percent  = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
                           validators=[MinValueValidator(0), MaxValueValidator(100)])
    taxa_credito_fixa     = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    taxa_debito_percent   = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"),
                           validators=[MinValueValidator(0), MaxValueValidator(100)])
    taxa_debito_fixa      = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"MP Config para {self.paroquia.nome}"


# ---------------------------------------------------------------------
# PreferÃªncias de ComunicaÃ§Ã£o
# ---------------------------------------------------------------------
class PreferenciasComunicacao(models.Model):
    FONTE_CHOICES = [
        ('form', 'FormulÃ¡rio/Portal'),
        ('admin', 'Admin'),
        ('import', 'ImportaÃ§Ã£o'),
    ]

    participante = models.OneToOneField('Participante', on_delete=models.CASCADE, related_name='prefs')
    whatsapp_marketing_opt_in = models.BooleanField(default=False, verbose_name="Aceita marketing no WhatsApp")
    whatsapp_optin_data = models.DateTimeField(null=True, blank=True)
    whatsapp_optin_fonte = models.CharField(max_length=20, choices=FONTE_CHOICES, default='admin')
    whatsapp_optin_prova = models.TextField(blank=True, null=True, help_text="Como foi coletado (ex.: checkbox, IP, data/hora)")
    politica_versao = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"PreferÃªncias de {self.participante.nome}"

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
# PolÃ­tica de Reembolso
# ---------------------------------------------------------------------
class PoliticaReembolso(models.Model):
    evento = models.OneToOneField(
        EventoAcampamento,
        on_delete=models.CASCADE,
        related_name='politica_reembolso',
        help_text="Cada evento pode ter (no mÃ¡ximo) uma polÃ­tica de reembolso."
    )
    ativo = models.BooleanField(default=True)
    permite_reembolso = models.BooleanField(
        default=True,
        help_text="Se desmarcado, o evento nÃ£o aceitarÃ¡ solicitaÃ§Ãµes de reembolso."
    )

    prazo_solicitacao_dias = models.PositiveIntegerField(
        default=7,
        help_text="Dias ANTES do inÃ­cio do evento para solicitar reembolso."
    )
    taxa_administrativa_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))],
        help_text="Percentual descontado no reembolso (0 a 100)."
    )

    descricao = models.TextField(
        blank=True,
        help_text="Detalhe as regras (ex.: Integral atÃ© 7 dias antes; apÃ³s isso, 70%)."
    )

    contato_email = models.EmailField(blank=True, null=True)
    contato_whatsapp = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="WhatsApp em E.164 (ex.: +5563920013103).",
        validators=[RegexValidator(regex=r'^\+55\d{10,11}$',
                                   message="Use +55 seguido de 10 ou 11 dÃ­gitos.")]
    )

    data_criacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PolÃ­tica de Reembolso"
        verbose_name_plural = "PolÃ­ticas de Reembolso"

    def __str__(self):
        return f"PolÃ­tica de Reembolso â€“ {self.evento.nome}"

    def clean(self):
        super().clean()
        if self.contato_whatsapp:
            norm = normalizar_e164_br(self.contato_whatsapp)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'contato_whatsapp': "Informe um telefone BR vÃ¡lido. Ex.: +5563920013103"})
            self.contato_whatsapp = norm

    def save(self, *args, **kwargs):
        if self.contato_whatsapp:
            norm = normalizar_e164_br(self.contato_whatsapp)
            if norm:
                self.contato_whatsapp = norm
        super().save(*args, **kwargs)


# models.py
class MercadoPagoOwnerConfig(models.Model):
    """
    Credenciais do Mercado Pago do DONO do sistema.
    Usado EXCLUSIVAMENTE para gerar PIX de repasse.
    """
    nome_exibicao = models.CharField(max_length=100, default="Admin do Sistema")

    # >>> suas credenciais MP
    access_token = models.CharField("Access Token", max_length=255)
    public_key   = models.CharField("Public Key", max_length=255, blank=True, null=True)

    # >>> dados da CHAVE PIX e identificaÃ§Ã£o do recebedor
    chave_pix       = models.CharField("Chave PIX do dono", max_length=140)  # e-mail, CPF/CNPJ, telefone ou aleatÃ³ria
    nome_recebedor  = models.CharField("Nome (recebedor PIX)", max_length=25)  # limite Pix/EMV recomenda <=25
    cidade_recebedor= models.CharField("Cidade (recebedor PIX)", max_length=15, default="SAO PAULO")  # recomenda <=15

    notificacao_webhook_url = models.URLField(blank=True, null=True, help_text="Opcional: URL pÃºblica do webhook de repasses")
    email_cobranca = models.EmailField(blank=True, null=True, help_text="E-mail que aparecerÃ¡ como pagador padrÃ£o")
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ConfiguraÃ§Ã£o MP (Dono)"
        verbose_name_plural = "ConfiguraÃ§Ãµes MP (Dono)"

    def __str__(self):
        return f"MP Dono ({'ativo' if self.ativo else 'inativo'})"



class Repasse(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PAGO = "pago", "Pago"
        CANCELADO = "cancelado", "Cancelado"

    paroquia = models.ForeignKey("inscricoes.Paroquia", on_delete=models.CASCADE, related_name="repasses")
    evento = models.ForeignKey("inscricoes.EventoAcampamento", on_delete=models.CASCADE, related_name="repasses")
    # base = arrecadado confirmado - taxas MP (dos pagamentos das inscriÃ§Ãµes)
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
        return f"Repasse {self.paroquia} / {self.evento} â€” {self.valor_repasse} ({self.status})"


# ---------------------------------------------------------------------
# MÃ­dias do Site (landing / institucional)
# ---------------------------------------------------------------------
class SiteImage(models.Model):
    """
    RepositÃ³rio central de imagens usadas no site (landing, pÃ¡ginas institucionais).
    Use 'key' para referenciar nas templates.
    """
    CATEGORIA_CHOICES = [
        ("hero", "Hero / Capa"),
        ("screenshot", "Screenshot"),
        ("logo", "Logo/Marca"),
        ("ilustracao", "IlustraÃ§Ã£o"),
        ("icone", "ÃƒÂcone"),
        ("banner", "Banner"),
        ("outro", "Outro"),
    ]

    key = models.SlugField("Chave Ãºnica", max_length=80, unique=True,
                           help_text="Ex.: dashboard, pagamentos, questionario-pronto")
    titulo = models.CharField("TÃ­tulo", max_length=120, blank=True)
    categoria = models.CharField("Categoria", max_length=20, choices=CATEGORIA_CHOICES, default="screenshot")
    imagem = CloudinaryField(verbose_name="Imagem", null=True, blank=True)
    alt_text = models.CharField("Texto alternativo (acessibilidade)", max_length=200, blank=True)
    legenda = models.CharField("Legenda (opcional)", max_length=200, blank=True)
    creditos = models.CharField("CrÃ©ditos (opcional)", max_length=200, blank=True)
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
    Leads do formulÃ¡rio 'Entre em contato' (landing).
    """
    nome = models.CharField(max_length=120)
    email = models.EmailField(db_index=True)
    whatsapp = models.CharField(
        max_length=20,
        help_text="WhatsApp em E.164 BR: +55DDDNÃšMERO (ex.: +5563920013103)",
        validators=[RegexValidator(
            regex=r'^\+55\d{10,11}$',
            message="Use +55 seguido de 10 ou 11 dÃ­gitos (ex.: +5563920013103).",
        )],
    )
    mensagem = models.TextField(blank=True)

    # ATENÃ‡ÃƒO: mantenha o MESMO nome usado no form/template (use 'consent_lgpd').
    consent_lgpd = models.BooleanField(default=False)

    origem = models.CharField(max_length=120, default="landing")

    # Auditoria (Ãºteis p/ analytics bÃ¡sicos)
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
        """Exibe os 2 Ãºltimos dÃ­gitos apenas."""
        if not self.whatsapp:
            return ""
        return self.whatsapp[:-2] + "â€Â¢â€Â¢"

    def clean(self):
        super().clean()
        # Normaliza/valida WhatsApp digitado no site (pode vir sem E.164)
        if self.whatsapp:
            norm = normalizar_e164_br(self.whatsapp)
            if not norm or not validar_e164_br(norm):
                raise ValidationError({'whatsapp': "Informe um telefone BR vÃ¡lido. Ex.: +5563920013103"})
            self.whatsapp = norm


@receiver(post_save, sender=LeadLanding)
def _leadlanding_enviar_emails(sender, instance: 'LeadLanding', created, **kwargs):
    if not created:
        return

    # E-mail para a pessoa
    assunto_user = "Recebemos sua mensagem â€” eismeaqui.app"
    texto_user = (
        f"OlÃ¡ {instance.nome},\n\n"
        "Recebemos sua mensagem no eismeaqui.app. Em breve retornaremos via e-mail ou WhatsApp.\n\n"
        "Deus abenÃ§oe!\nEquipe eismeaqui.app"
    )
    html_user = f"""
    <html><body style="font-family:Arial,sans-serif;color:#0f172a">
      <p>OlÃ¡ <strong>{instance.nome}</strong>,</p>
      <p>Recebemos sua mensagem no <strong>eismeaqui.app</strong>. Em breve retornaremos via e-mail ou WhatsApp.</p>
      <p>Deus abenÃ§oe!<br/>Equipe eismeaqui.app</p>
    </body></html>
    """
    try:
        m1 = EmailMultiAlternatives(assunto_user, texto_user, settings.DEFAULT_FROM_EMAIL, [instance.email])
        m1.attach_alternative(html_user, "text/html")
        m1.send(fail_silently=True)
    except Exception:
        pass

    # E-mail interno (para vocÃª/equipe)
    destino_admin = getattr(settings, "SALES_INBOX", settings.DEFAULT_FROM_EMAIL)
    assunto_admin = f"[Landing] Novo contato: {instance.nome}"
    html_admin = f"""
    <html><body style="font-family:Arial,sans-serif;color:#0f172a">
      <h3>Novo contato recebido</h3>
      <p><strong>Nome:</strong> {instance.nome}</p>
      <p><strong>E-mail:</strong> {instance.email}</p>
      <p><strong>WhatsApp:</strong> {instance.whatsapp}</p>
      <p><strong>Mensagem:</strong><br/>{instance.mensagem or 'â€”'}</p>
      <p><small>Origem: {instance.origem} â€Â¢ Data: {timezone.localtime(instance.created_at).strftime('%d/%m/%Y %H:%M')}</small></p>
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
        return f"{self.paroquia.nome} â€Â¢ {self.titulo}"


class EventoComunitario(models.Model):
    paroquia = models.ForeignKey("inscricoes.Paroquia", on_delete=models.CASCADE, related_name="eventos_comunidade")
    nome = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, blank=True)  # Ãºnico dentro da parÃ³quia
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
        return f"{self.paroquia.nome} â€Â¢ {self.nome}"


# ---------------------------------------------------------------------
# CatÃ¡logo fixo de Grupos (com cores) e MinistÃ©rios + AlocaÃ§Ãµes por evento
# ---------------------------------------------------------------------
from django.core.validators import RegexValidator

# Paleta padrÃ£o (nome Ã¢â€ â€™ hex). Pode ampliar quando quiser.
CORES_PADRAO = {
    "Amarelo":   "#F59E0B",
    "Vermelho":  "#EF4444",
    "Azul":      "#3B82F6",
    "Verde":     "#10B981",
    "Laranja":   "#FB923C",
    "Roxo":      "#8B5CF6",
    "Rosa":      "#EC4899",
    "Ciano":     "#06B6D4",
    "Lima":      "#84CC16",
    "Cinza":     "#6B7280",
}

HEX_VALIDATOR = RegexValidator(
    regex=r"^#([A-Fa-f0-9]{6})$",
    message="Use um HEX no formato #RRGGBB (ex.: #3B82F6).",
)

class Grupo(models.Model):
    """
    CatÃ¡logo global de grupos. NÃƒO depende do evento.
    A cor Ã© escolhida do catÃ¡logo e guardamos o HEX para exibir nos relatÃ³rios/fichas.
    """
    nome = models.CharField(max_length=100, unique=True)
    cor_nome = models.CharField(
        max_length=20,
        choices=[(n, n) for n in CORES_PADRAO.keys()],
        default="Amarelo",
        help_text="Nome da cor do catÃ¡logo (ex.: Amarelo, Vermelho, Azul...)",
    )
    cor_hex = models.CharField(
        max_length=7,  # #RRGGBB
        validators=[HEX_VALIDATOR],
        default=CORES_PADRAO["Amarelo"],
        help_text="Hex da cor (preenchido automaticamente ao salvar).",
    )
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["nome"]

    def clean(self):
        super().clean()
        # mantÃ©m hex coerente com o nome da cor
        if self.cor_nome in CORES_PADRAO:
            self.cor_hex = CORES_PADRAO[self.cor_nome]

    def save(self, *args, **kwargs):
        if self.cor_nome in CORES_PADRAO:
            self.cor_hex = CORES_PADRAO[self.cor_nome]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.cor_nome})"


class Ministerio(models.Model):
    """
    CatÃ¡logo global de ministÃ©rios. NÃƒO depende do evento.
    """
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


# ======================= ALOCAÃ‡Ã•ES por evento =======================

class AlocacaoMinisterio(models.Model):
    """
    Liga uma inscriÃ§Ã£o (evento Servos/Servos de Casais) a um MinistÃ©rio no EVENTO da inscriÃ§Ã£o.
    Garante no mÃ¡ximo 1 coordenador por (evento, ministÃ©rio).
    """
    inscricao = models.OneToOneField(
        "Inscricao",
        on_delete=models.CASCADE,
        related_name="alocacao_ministerio",
        help_text="A inscriÃ§Ã£o deste servo (no evento de Servos).",
    )
    # Mantemos para filtros/relatÃ³rios; Ã© sempre igual a inscricao.evento
    evento = models.ForeignKey(
        "EventoAcampamento",
        on_delete=models.CASCADE,
        related_name="alocacoes_ministerio",
    )
    ministerio = models.ForeignKey(
        "Ministerio",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="alocacoes",
    )
    funcao = models.CharField(
        max_length=100,
        blank=True, null=True,
        help_text="Ex.: CoordenaÃ§Ã£o, Liturgia, MÃºsica..."
    )
    is_coordenador = models.BooleanField(
        default=False,
        verbose_name="Ã‰ coordenador(a) do ministÃ©rio?"
    )
    data_alocacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Um coordenador por ministÃ©rio em cada evento
            models.UniqueConstraint(
                fields=["evento", "ministerio"],
                condition=Q(is_coordenador=True),
                name="uniq_um_coordenador_por_ministerio_em_evento",
            ),
        ]
        indexes = [
            models.Index(fields=["evento"]),
            models.Index(fields=["ministerio"]),
            models.Index(fields=["is_coordenador"]),
        ]

    # --- ValidaÃ§Ã£o de domÃ­nio ---
    def clean(self):
        super().clean()

        # Defina 'ev' com prioridade para inscricao.evento (fonte da verdade)
        ev = None
        if self.inscricao_id:
            ev = getattr(self.inscricao, "evento", None)
        if not ev and self.evento_id:
            ev = self.evento

        # 1) evento deve bater com inscricao.evento (quando ambos presentes)
        if self.inscricao_id and self.evento_id:
            if self.inscricao.evento_id != self.evento_id:
                # Erro geral (nÃ£o prenda a 'evento' para evitar ValueError no form)
                raise ValidationError("O evento da alocaÃ§Ã£o deve ser o mesmo da inscriÃ§Ã£o.")

        # 2) SÃ³ permitir em eventos de Servos (inclui 'servos de casais')
        tipo = (getattr(ev, "tipo", "") or "").lower()
        if tipo and ("servos" not in tipo):
            raise ValidationError("AtribuiÃ§Ã£o de ministÃ©rio sÃ³ Ã© permitida para eventos de Servos.")

        # 3) Impedir 2 coordenadores (checa alÃ©m do UniqueConstraint para erro amigÃ¡vel)
        if self.is_coordenador and self.ministerio_id and ev:
            qs = type(self).objects.filter(
                evento_id=ev.id,
                ministerio_id=self.ministerio_id,
                is_coordenador=True,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError("Este ministÃ©rio jÃ¡ possui um(a) coordenador(a) neste evento.")

        # (Opcional) Se MinistÃ©rio for escopo do evento, valide coerÃªncia:
        # if self.ministerio and hasattr(self.ministerio, "evento_id") and self.ministerio.evento_id != ev.id:
        #     raise ValidationError("Este ministÃ©rio nÃ£o pertence a este evento.")

    # --- Sincronismo e validaÃ§Ã£o antes de persistir ---
    def save(self, *args, **kwargs):
        # Sempre sincroniza evento <- inscricao.evento
        if self.inscricao_id:
            ev_id = getattr(self.inscricao, "evento_id", None)
            if ev_id and self.evento_id != ev_id:
                self.evento_id = ev_id
        # Valida tudo jÃ¡ com o evento sincronizado
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        p = getattr(self.inscricao, "participante", None)
        nome = getattr(p, "nome", "Participante")
        m = getattr(self.ministerio, "nome", None) or "Sem ministÃ©rio"
        ev_nome = getattr(self.evento, "nome", "Evento")
        tag = " (Coord.)" if self.is_coordenador else ""
        return f"{nome}{tag} Ã¢â€ â€™ {m} @ {ev_nome}"

class AlocacaoGrupo(models.Model):
    """
    Liga uma inscriÃ§Ã£o a um Grupo (global).
    Pode ser usada em QUALQUER tipo de evento.
    O campo `evento` Ã© sempre sincronizado com `inscricao.evento`.
    """
    inscricao = models.OneToOneField(
        "Inscricao",
        on_delete=models.CASCADE,
        related_name="alocacao_grupo",
    )
    evento = models.ForeignKey(
        "EventoAcampamento",
        on_delete=models.CASCADE,
        related_name="alocacoes_grupo",
    )
    grupo = models.ForeignKey(
        "Grupo",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="alocacoes",
    )
    funcao = models.CharField(max_length=100, blank=True)
    is_coordenador = models.BooleanField(default=False)
    data_alocacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["evento"]),
            models.Index(fields=["grupo"]),
        ]

    def clean(self):
        super().clean()

        # 1) CoerÃªncia: evento da alocaÃ§Ã£o TEM que ser o mesmo da inscriÃ§Ã£o
        if self.inscricao_id and self.evento_id:
            if self.evento_id != self.inscricao.evento_id:
                # erro geral (nÃ£o amarra em campo especÃ­fico do form)
                raise ValidationError("O evento da alocaÃ§Ã£o deve ser o mesmo da inscriÃ§Ã£o.")

        # 2) (Intencionalmente REMOVIDO)
        #    NÃ£o hÃ¡ mais restriÃ§Ã£o por tipo de evento (antes exigia 'servos').

        # 3) Se um dia Grupo fosse por evento, validar aqui (nÃ£o Ã© o caso atual).

    def save(self, *args, **kwargs):
        # Sincroniza sempre: evento <- inscricao.evento
        if self.inscricao_id:
            ev_id = getattr(self.inscricao, "evento_id", None)
            if ev_id and self.evento_id != ev_id:
                self.evento_id = ev_id

        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        p = getattr(self.inscricao, "participante", None)
        nome = getattr(p, "nome", "Participante")
        g = getattr(self.grupo, "nome", None) or "Sem grupo"
        ev_nome = getattr(self.evento, "nome", "Evento")
        return f"{nome} Ã¢â€ â€™ {g} @ {ev_nome}"