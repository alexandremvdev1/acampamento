from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from django.utils.html import format_html

from .utils.phones import normalizar_e164_br, validar_e164_br
from .models import (
    Paroquia, Participante, EventoAcampamento, Inscricao, Pagamento,
    InscricaoSenior, InscricaoJuvenil, InscricaoMirim, InscricaoServos,
    InscricaoCasais, InscricaoEvento, InscricaoRetiro,   # <- NOVOS TIPOS
    User, PastoralMovimento, Contato, Conjuge, MercadoPagoConfig,
    PoliticaPrivacidade, VideoEventoAcampamento, CrachaTemplate,
    PreferenciasComunicacao, PoliticaReembolso,
)

# ======================= Paróquia =======================
class ParoquiaAdminForm(forms.ModelForm):
    class Meta:
        model = Paroquia
        fields = "__all__"
        widgets = {
            "telefone": forms.TextInput(attrs={
                "placeholder": "+5563920013103",
                "pattern": r"\+55\d{10,11}",
                "title": "Use +55 seguido de 10 ou 11 dígitos (ex.: +5563920013103)",
                "inputmode": "numeric",
            })
        }

    def clean_telefone(self):
        raw = self.cleaned_data.get("telefone", "")
        norm = normalizar_e164_br(raw)
        if not norm or not validar_e164_br(norm):
            raise forms.ValidationError("Informe um telefone BR válido. Ex.: +5563920013103")
        return norm

@admin.register(Paroquia)
class ParoquiaAdmin(admin.ModelAdmin):
    form = ParoquiaAdminForm
    list_display = ('nome', 'cidade', 'estado', 'responsavel', 'email', 'telefone', 'status')
    search_fields = ('nome', 'cidade', 'responsavel', 'email', 'telefone')
    list_filter = ('estado', 'status')
    actions = ["normalizar_telefones"]

    @admin.action(description="Normalizar telefones selecionados para E.164 (+55)")
    def normalizar_telefones(self, request, queryset):
        ok, fail = 0, 0
        for p in queryset:
            norm = normalizar_e164_br(p.telefone)
            if norm and validar_e164_br(norm):
                if p.telefone != norm:
                    p.telefone = norm
                    p.save(update_fields=["telefone"])
                ok += 1
            else:
                fail += 1
        if ok:
            messages.success(request, f"Telefones normalizados: {ok}.")
        if fail:
            messages.warning(request, f"Registros não normalizados (verificar formato): {fail}.")


# ===================== Participante =====================
class PreferenciasComunicacaoInline(admin.StackedInline):
    """Inline para editar o opt-in de marketing no WhatsApp por participante."""
    model = PreferenciasComunicacao
    can_delete = False
    extra = 0
    fieldsets = (
        (None, {
            "fields": (
                "whatsapp_marketing_opt_in",
                "whatsapp_optin_data",
                "whatsapp_optin_fonte",
                "whatsapp_optin_prova",
                "politica_versao",
            )
        }),
    )
    readonly_fields = ("whatsapp_optin_data",)

@admin.register(Participante)
class ParticipanteAdmin(admin.ModelAdmin):
    list_display = (
        'nome', 'cpf', 'telefone', 'email',
        'cidade', 'estado',
        'whatsapp_mkt',  # coluna booleana
        'qr_token',
        'qr_code_img',
    )
    search_fields = ('nome', 'cpf', 'email', 'cidade', 'telefone')
    list_filter = ('estado', 'cidade', 'prefs__whatsapp_marketing_opt_in')
    readonly_fields = ('qr_token',)
    inlines = [PreferenciasComunicacaoInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('prefs')

    def whatsapp_mkt(self, obj):
        prefs = getattr(obj, 'prefs', None)
        return bool(prefs and prefs.whatsapp_marketing_opt_in)
    whatsapp_mkt.boolean = True
    whatsapp_mkt.short_description = "WhatsApp (mkt)"

    def qr_code_img(self, obj):
        if not obj.qr_token:
            return "-"
        url = reverse('inscricoes:qr_code_png', args=[obj.qr_token])
        return format_html('<img src="{}" width="40" height="40" style="border:1px solid #ccc;"/>', url)
    qr_code_img.short_description = "QR Code"

    fieldsets = (
        (None, {
            'fields': (
                'nome', 'cpf', 'telefone', 'email',
                'CEP', 'endereco', 'numero', 'bairro', 'cidade', 'estado',
                'foto',
            )
        }),
        ('QR Code', {'fields': ('qr_token',)}),
    )

    # Ações em massa: opt-in marketing
    @admin.action(description="Marcar opt-in de marketing (WhatsApp)")
    def marcar_optin_marketing(self, request, queryset):
        from django.utils import timezone
        count = 0
        for p in queryset:
            prefs, _ = PreferenciasComunicacao.objects.get_or_create(participante=p)
            if not prefs.whatsapp_marketing_opt_in:
                prefs.whatsapp_marketing_opt_in = True
                prefs.whatsapp_optin_data = timezone.now()
                prefs.whatsapp_optin_fonte = 'admin'
                prefs.whatsapp_optin_prova = f'Admin: {request.user.username}'
                prefs.save()
                count += 1
        self.message_user(request, f"{count} participante(s) marcados com opt-in de marketing.")

    @admin.action(description="Remover opt-in de marketing (WhatsApp)")
    def remover_optin_marketing(self, request, queryset):
        count = 0
        for p in queryset:
            prefs = getattr(p, 'prefs', None)
            if prefs and prefs.whatsapp_marketing_opt_in:
                prefs.whatsapp_marketing_opt_in = False
                prefs.save()
                count += 1
        self.message_user(request, f"{count} participante(s) com opt-in de marketing removido.")

    actions = ['marcar_optin_marketing', 'remover_optin_marketing']


# ======================= Eventos ========================
@admin.register(EventoAcampamento)
class EventoAcampamentoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'tipo', 'paroquia', 'data_inicio', 'data_fim', 'inicio_inscricoes', 'fim_inscricoes', 'slug')
    list_filter = ('tipo', 'paroquia')
    prepopulated_fields = {'slug': ('nome',)}
    search_fields = ('nome', 'paroquia__nome')


# ====================== Inscrições ======================
@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = (
        'participante', 'evento', 'paroquia', 'data_inscricao',
        'foi_selecionado', 'pagamento_confirmado', 'inscricao_concluida'
    )
    list_filter = ('evento__tipo', 'evento', 'paroquia', 'foi_selecionado', 'pagamento_confirmado')
    search_fields = ('participante__nome', 'evento__nome', 'paroquia__nome')


# ======================= Pagamento ======================
@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ('inscricao', 'metodo', 'valor', 'status', 'data_pagamento', 'transacao_id')
    list_filter = ('status', 'metodo')
    search_fields = ('inscricao__participante__nome', 'transacao_id')


# ========== Inscrições específicas por tipo ============
BASE_LIST_DISPLAY = (
    'inscricao', 'data_nascimento', 'paroquia', 'batizado',
    'alergia_alimento', 'qual_alergia_alimento',
    'alergia_medicamento', 'qual_alergia_medicamento',
)
BASE_LIST_FILTER = ('paroquia', 'batizado', 'alergia_alimento', 'alergia_medicamento')
BASE_SEARCH = (
    'inscricao__participante__nome', 'paroquia__nome',
    'qual_alergia_alimento', 'qual_alergia_medicamento',
)

@admin.register(InscricaoSenior)
class InscricaoSeniorAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

@admin.register(InscricaoJuvenil)
class InscricaoJuvenilAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

@admin.register(InscricaoMirim)
class InscricaoMirimAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

@admin.register(InscricaoServos)
class InscricaoServosAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

# ---- NOVOS TIPOS ----
@admin.register(InscricaoCasais)
class InscricaoCasaisAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

@admin.register(InscricaoEvento)
class InscricaoEventoAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH

@admin.register(InscricaoRetiro)
class InscricaoRetiroAdmin(admin.ModelAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH


# ======================== Usuário =======================
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'tipo_usuario', 'paroquia', 'is_staff', 'is_active')
    list_filter = ('tipo_usuario', 'is_staff', 'is_active', 'paroquia')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informações Pessoais', {'fields': ('email', 'tipo_usuario', 'paroquia')}),
        ('Permissões', {'fields': ('is_staff', 'is_active', 'groups', 'user_permissions')}),
        ('Datas importantes', {'fields': ('last_login', 'date_joined')}),
    )
    search_fields = ('username', 'email', 'tipo_usuario')
    ordering = ('username',)
    filter_horizontal = ('groups', 'user_permissions',)


# ======================== Diversos ======================
class PoliticaPrivacidadeAdminForm(forms.ModelForm):
    class Meta:
        model = PoliticaPrivacidade
        fields = "__all__"
        widgets = {
            "telefone_contato": forms.TextInput(attrs={
                "placeholder": "+5563920013103",
                "pattern": r"\+55\d{10,11}",
                "title": "Use +55 seguido de 10 ou 11 dígitos (ex.: +5563920013103)",
                "inputmode": "numeric",
            })
        }

    def clean_telefone_contato(self):
        raw = self.cleaned_data.get("telefone_contato") or ""
        if not raw:
            return raw
        norm = normalizar_e164_br(raw)
        if not norm or not validar_e164_br(norm):
            raise forms.ValidationError("Informe um telefone BR válido. Ex.: +5563920013103")
        return norm

@admin.register(PoliticaPrivacidade)
class PoliticaPrivacidadeAdmin(admin.ModelAdmin):
    form = PoliticaPrivacidadeAdminForm
    list_display = ("__str__", "email_contato", "telefone_contato", "estado")

@admin.register(VideoEventoAcampamento)
class VideoEventoAcampamentoAdmin(admin.ModelAdmin):
    list_display = ('evento', 'titulo', 'arquivo')

@admin.register(PastoralMovimento)
class PastoralMovimentoAdmin(admin.ModelAdmin):
    list_display = ['nome']
    search_fields = ['nome']

@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'grau_parentesco', 'ja_e_campista', 'inscricao')
    search_fields = ('nome', 'telefone', 'grau_parentesco', 'inscricao__participante__nome')
    list_filter = ('ja_e_campista',)

@admin.register(Conjuge)
class ConjugeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'inscricao_participante', 'conjuge_inscrito', 'ja_e_campista')
    list_filter = ('conjuge_inscrito', 'ja_e_campista')
    search_fields = ('nome', 'inscricao__participante__nome', 'inscricao__participante__cpf')

    def inscricao_participante(self, obj):
        return obj.inscricao.participante.nome
    inscricao_participante.short_description = 'Participante'

@admin.register(CrachaTemplate)
class CrachaTemplateAdmin(admin.ModelAdmin):
    list_display = ("nome",)

@admin.register(MercadoPagoConfig)
class MercadoPagoConfigAdmin(admin.ModelAdmin):
    list_display = ('paroquia', 'public_key', 'sandbox_mode')
    list_filter  = ('sandbox_mode',)
    search_fields = ('paroquia__nome',)

@admin.register(PoliticaReembolso)
class PoliticaReembolsoAdmin(admin.ModelAdmin):
    list_display = (
        'evento', 'ativo', 'permite_reembolso',
        'prazo_solicitacao_dias', 'taxa_administrativa_percent',
        'contato_email', 'contato_whatsapp',
        'data_atualizacao',
    )
    list_filter = ('ativo', 'permite_reembolso',)
    search_fields = ('evento__nome', 'contato_email', 'contato_whatsapp')
