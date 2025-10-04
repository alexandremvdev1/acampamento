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
class InscricaoStatus(models.TextChoices):
    RASCUNHO        = "draft",         "Rascunho"
    ENVIADA         = "submitted",     "Enviada"
    EM_ANALISE      = "under_review",  "Em análise"
    APROVADA        = "approved",      "Aprovada"            # triagem OK
    LISTA_ESPERA    = "waitlist",      "Lista de espera"
    REJEITADA       = "rejected",      "Rejeitada"

    CONVOCADA       = "selected",      "Selecionada/Convocada"
    PAG_PENDENTE    = "pay_pending",   "Pagamento pendente"
    PAG_CONFIRMADO  = "pay_confirmed", "Pagamento confirmado"

    CANCEL_USUARIO  = "cancel_user",   "Cancelada pelo usuário"
    CANCEL_ADMIN    = "cancel_admin",  "Cancelada pela paróquia"

    REEMB_SOL       = "refund_req",    "Reembolso solicitado"
    REEMB_APROV     = "refund_ok",     "Reembolso aprovado"
    REEMB_NEG       = "refund_den",    "Reembolso negado"


class Inscricao(models.Model):
    # ----- chaves -----
    participante = models.ForeignKey('Participante', on_delete=models.CASCADE)
    evento       = models.ForeignKey('EventoAcampamento', on_delete=models.CASCADE)
    paroquia     = models.ForeignKey('Paroquia', on_delete=models.CASCADE, related_name='inscricoes')
    data_inscricao = models.DateTimeField(auto_now_add=True)

    # ----- status único -----
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

    # ----- extras já existentes no seu modelo -----
    ja_e_campista = models.BooleanField(default=False, verbose_name="Já é campista?")
    tema_acampamento = models.CharField(max_length=200, blank=True, null=True,
                                        verbose_name="Se sim, qual tema do acampamento que participou?")

    cpf_conjuge = models.CharField(max_length=14, blank=True, null=True,
                                   help_text="CPF do cônjuge (com ou sem máscara)")

    inscricao_pareada = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='pareada_por',
        help_text="Outra inscrição (cônjuge) vinculada"
    )

    # Responsáveis / Contato de Emergência (mantidos)
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
        return f"{self.participante.nome} – {self.evento.nome} – {self.paroquia.nome}"

    # ------------------------------------------------------------
    # URLs úteis
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
    # Leitura rápida (derivados do status)
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
    # Mapeamento da base por tipo (como já fazia)
    # ------------------------------------------------------------
    def _get_baseinscricao_model(self):
        tipo = (self.evento.tipo or "").strip().lower()
        # importe os modelos corretos ou adie o import para evitar ciclos
        from . import inscricaosenior as _s   # ajuste para o caminho real
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
            raise ValidationError("Não pode parear consigo mesmo.")
        if outra.evento_id != self.evento_id:
            raise ValidationError("A inscrição pareada deve ser do mesmo evento.")
        with transaction.atomic():
            self.inscricao_pareada = outra
            self.save(update_fields=['inscricao_pareada'])
            if outra.par != self:
                outra.inscricao_pareada = self
                outra.save(update_fields=['inscricao_pareada'])
            # Se evento é casais e um deles já estava selecionado, mantém coerência
            if (self.evento.tipo or '').lower() == 'casais':
                if self.is_selecionada and not outra.is_selecionada:
                    outra.mudar_status(InscricaoStatus.CONVOCADA, motivo="Pareado com selecionado")
                elif outra.is_selecionada and not self.is_selecionada:
                    self.mudar_status(InscricaoStatus.CONVOCADA, motivo="Pareado com selecionado")

    def desparear(self):
        if self.par:
            outra = self.par
            with transaction.atomic():
                self.inscricao_pareada = None
                self.save(update_fields=['inscricao_pareada'])
                if outra.par == self:
                    outra.inscricao_pareada = None
                    outra.save(update_fields=['inscricao_pareada'])

    # utils para CPF do cônjuge
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
    # Pagamento casais: propagar ao par
    # ------------------------------------------------------------
    def _propagar_pagamento_para_par(self, confirmado: bool):
        if (self.evento.tipo or '').lower() != 'casais':
            return
        par = self.par
        if not par:
            return
        if par.pagamento_confirmado == confirmado and par.inscricao_concluida == confirmado:
            return
        with transaction.atomic():
            type(self).objects.filter(pk=par.pk).update(
                pagamento_confirmado=confirmado,
                inscricao_concluida=confirmado,
                status=InscricaoStatus.PAG_CONFIRMADO if confirmado else InscricaoStatus.CONVOCADA,
            )

    # ------------------------------------------------------------
    # Validações
    # ------------------------------------------------------------
    def clean(self):
        super().clean()
        # pareamento: mesmo evento
        if self.inscricao_pareada:
            if self.inscricao_pareada_id == self.id:
                raise ValidationError({'inscricao_pareada': "Não é possível parear com a própria inscrição."})
            if self.inscricao_pareada.evento_id != self.evento_id:
                raise ValidationError({'inscricao_pareada': "A inscrição pareada deve ser do mesmo evento."})

        # campista: precisa do tema
        if self.ja_e_campista and not self.tema_acampamento:
            raise ValidationError({'tema_acampamento': "Informe o tema do acampamento que participou."})

        # evento de Servos precisa ter principal permitindo
        if (self.evento.tipo or "").lower() == "servos":
            principal = getattr(self.evento, "evento_relacionado", None)
            if not principal:
                raise ValidationError({"evento": "Evento de Servos sem vínculo com evento principal."})
            if not getattr(principal, "permitir_inscricao_servos", False):
                raise ValidationError("Inscrições de Servos estão desabilitadas para este evento.")

    # ------------------------------------------------------------
    # Disparos (stubs — substitua pelas suas implementações)
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

    # —— cole aqui suas versões atuais, se preferir ——
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
    # Máquina de estados e transições
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
        """Aplica transição validada e dispara eventos usuais."""
        if novo_status == self.status:
            return False
        permitidos = self._NEXT.get(self.status, set())
        if novo_status not in permitidos:
            raise ValidationError(
                f"Transição inválida: {self.get_status_display()} → "
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

            # disparos
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

        return True

    # ------------------------------------------------------------
    # SAVE: reforça validações + mantém comportamento legado
    # ------------------------------------------------------------
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        self.full_clean()

        # — comportamento legado: se alguém setou os booleans diretamente,
        #   convertemos para o status correspondente antes de salvar.
        #   (a ideia é facilitar a transição gradual do código antigo)
        status_alvo = None
        if self.pagamento_confirmado:
            status_alvo = InscricaoStatus.PAG_CONFIRMADO
        elif self.foi_selecionado and not self.pagamento_confirmado:
            # se “selecionado” e sem pgto, preferimos “pay_pending”
            status_alvo = InscricaoStatus.PAG_PENDENTE
        elif self.inscricao_enviada and self.status == InscricaoStatus.RASCUNHO:
            status_alvo = InscricaoStatus.ENVIADA

        if status_alvo and status_alvo != self.status:
            # use a máquina para disparar efeitos; se não puder (ex.: nas primeiras criações), apenas seta
            try:
                self.mudar_status(status_alvo, motivo="Autoajuste booleans→status")
                return  # mudar_status já salvou
            except ValidationError:
                self.status = status_alvo

        # espelha booleans corretos do status atual
        self._espelhar_booleans()

        super().save(*args, **kwargs)

        # pós-criação: garante base + tenta parear por CPF do cônjuge
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


# ------------------------------------------------------------
# Sinal: tentativa de parear assim que criar (como você já fazia)
# ------------------------------------------------------------
@receiver(post_save, sender=Inscricao)
def _parear_apos_criar(sender, instance: 'Inscricao', created, **kwargs):
    if not created:
        return
    # 1) tentar com o cpf_conjuge desta inscrição
    try:
        if instance.cpf_conjuge and instance.par is None:
            instance.tentar_vincular_conjuge()
    except Exception:
        pass

    # 2) inverso: achar quem informou o CPF deste participante
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
                c.set_pareada(instance)
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
# Catálogo fixo de Grupos (com cores) e Ministérios + Alocações por evento
# ---------------------------------------------------------------------
from django.core.validators import RegexValidator

# Paleta padrão (nome → hex). Pode ampliar quando quiser.
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
    Catálogo global de grupos. NÃO depende do evento.
    A cor é escolhida do catálogo e guardamos o HEX para exibir nos relatórios/fichas.
    """
    nome = models.CharField(max_length=100, unique=True)
    cor_nome = models.CharField(
        max_length=20,
        choices=[(n, n) for n in CORES_PADRAO.keys()],
        default="Amarelo",
        help_text="Nome da cor do catálogo (ex.: Amarelo, Vermelho, Azul...)",
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
        # mantém hex coerente com o nome da cor
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
    Catálogo global de ministérios. NÃO depende do evento.
    """
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


# ======================= ALOCAÇÕES por evento =======================

class AlocacaoMinisterio(models.Model):
    """
    Liga uma inscrição (que deve ser de um evento 'servos') a um Ministério (global) em um EVENTO específico.
    Garante no máximo 1 coordenador por (evento, ministério).
    """
    inscricao = models.OneToOneField(
        "Inscricao",
        on_delete=models.CASCADE,
        related_name="alocacao_ministerio",
        help_text="A inscrição deste servo (no evento de Servos).",
    )
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
        help_text="Ex.: Coordenação, Liturgia, Música..."
    )
    is_coordenador = models.BooleanField(
        default=False,
        verbose_name="É coordenador(a) do ministério?"
    )
    data_alocacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Um coordenador por ministério em cada evento
        constraints = [
            models.UniqueConstraint(
                fields=["evento", "ministerio"],
                condition=Q(is_coordenador=True),
                name="uniq_um_coordenador_por_ministerio_em_evento",
            )
        ]

    def clean(self):
        super().clean()
        # Inscrição e evento devem bater
        if self.inscricao and self.evento and self.inscricao.evento_id != self.evento_id:
            raise ValidationError({"evento": "O evento da alocação deve ser o mesmo da inscrição."})

        # Só em eventos de Servos
        if self.evento and (self.evento.tipo or "").lower() != "servos":
            raise ValidationError({"evento": "Atribuição de ministério só é permitida para eventos de Servos."})

        # Impedir 2 coordenadores
        if self.is_coordenador and self.ministerio_id:
            qs = type(self).objects.filter(
                evento_id=self.evento_id,
                ministerio_id=self.ministerio_id,
                is_coordenador=True
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"is_coordenador": "Este ministério já possui um(a) coordenador(a) neste evento."})

    def __str__(self):
        tag = " (Coord.)" if self.is_coordenador else ""
        nome_min = self.ministerio.nome if self.ministerio else "Sem ministério"
        return f"{self.inscricao.participante.nome}{tag} → {nome_min} @ {self.evento.nome}"


class AlocacaoGrupo(models.Model):
    """
    Liga uma inscrição (que deve ser de um evento 'servos') a um Grupo (global) em um EVENTO específico.
    """
    inscricao = models.OneToOneField(
        "Inscricao",
        on_delete=models.CASCADE,
        related_name="alocacao_grupo"
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
        related_name="alocacoes"
    )
    data_alocacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["evento"]),
            models.Index(fields=["grupo"]),
        ]

    def clean(self):
        super().clean()
        # Inscrição e evento devem bater
        if self.inscricao and self.evento and self.inscricao.evento_id != self.evento_id:
            raise ValidationError({"evento": "O evento da alocação deve ser o mesmo da inscrição."})

        # Só em eventos de Servos
        if self.evento and (self.evento.tipo or "").lower() != "servos":
            raise ValidationError({"evento": "Atribuição de grupo só é permitida para eventos de Servos."})

    def __str__(self):
        g = self.grupo.nome if self.grupo else "Sem grupo"
        return f"{self.inscricao.participante.nome} → {g} @ {self.evento.nome}"
