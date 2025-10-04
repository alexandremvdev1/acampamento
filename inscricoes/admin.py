from django import forms
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone

from .utils.phones import normalizar_e164_br, validar_e164_br
from .models import (
    Paroquia, Participante, EventoAcampamento, Inscricao, Pagamento,
    InscricaoSenior, InscricaoJuvenil, InscricaoMirim, InscricaoServos,
    InscricaoCasais, InscricaoEvento, InscricaoRetiro,
    User, PastoralMovimento, Contato, Conjuge, MercadoPagoConfig,
    PoliticaPrivacidade, VideoEventoAcampamento, CrachaTemplate,
    PreferenciasComunicacao, PoliticaReembolso,
    MercadoPagoOwnerConfig, Repasse, SiteImage, LeadLanding, SiteVisit,
    Grupo, Ministerio, AlocacaoGrupo, AlocacaoMinisterio, Filho
)

# =========================================================
# Mixin: limita ao escopo da paróquia do usuário (admin_paroquia)
# =========================================================
class SomenteMinhaParoquiaAdmin(admin.ModelAdmin):
    """
    Use este mixin em modelos que tenham FK direta 'paroquia'.
    - Filtra queryset pela paróquia do usuário (se não for super/admin_geral).
    - Oculta o campo 'paroquia' no form para admin paroquial e seta automaticamente.
    - Em FKs, filtra opções para a paróquia do usuário (ex.: evento).
    """
    paroquia_field_name = "paroquia"
    fk_limitadas_por_paroquia = ("evento",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        paroquia_id = getattr(user, "paroquia_id", None)
        if paroquia_id and self.paroquia_field_name in [f.name for f in self.model._meta.fields]:
            return qs.filter(**{self.paroquia_field_name: paroquia_id})
        return qs.none()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        user = request.user
        if (not getattr(user, "is_superuser", False)
            and getattr(user, "tipo_usuario", "") != "admin_geral"
            and getattr(user, "paroquia_id", None)
            and self.paroquia_field_name in form.base_fields):
            form.base_fields[self.paroquia_field_name].widget = forms.HiddenInput()
            form.base_fields[self.paroquia_field_name].required = False
        return form

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user
        if (not getattr(user, "is_superuser", False)
            and getattr(user, "tipo_usuario", "") != "admin_geral"
            and getattr(user, "paroquia_id", None)):

            if db_field.name == self.paroquia_field_name:
                kwargs["queryset"] = Paroquia.objects.filter(pk=user.paroquia_id)

            if db_field.name in getattr(self, "fk_limitadas_por_paroquia", []):
                try:
                    kwargs["queryset"] = db_field.remote_field.model.objects.filter(paroquia=user.paroquia)
                except Exception:
                    pass

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        user = request.user
        if (not getattr(user, "is_superuser", False)
            and getattr(user, "tipo_usuario", "") != "admin_geral"
            and getattr(user, "paroquia", None)
            and hasattr(obj, self.paroquia_field_name)
            and not getattr(obj, self.paroquia_field_name, None)):
            setattr(obj, self.paroquia_field_name, user.paroquia)
        super().save_model(request, obj, form, change)


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
        'whatsapp_mkt',
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

    @admin.action(description="Marcar opt-in de marketing (WhatsApp)")
    def marcar_optin_marketing(self, request, queryset):
        from django.utils import timezone as _tz
        count = 0
        for p in queryset:
            prefs, _ = PreferenciasComunicacao.objects.get_or_create(participante=p)
            if not prefs.whatsapp_marketing_opt_in:
                prefs.whatsapp_marketing_opt_in = True
                prefs.whatsapp_optin_data = _tz.now()
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
class EventoAcampamentoAdmin(SomenteMinhaParoquiaAdmin):
    list_display = (
        'nome', 'tipo', 'paroquia', 'data_inicio', 'data_fim',
        'inicio_inscricoes', 'fim_inscricoes', 'slug',
        'permitir_inscricao_servos', 'servos_vinculado', 'status_servos'
    )
    list_filter = ('tipo', 'paroquia', 'permitir_inscricao_servos')
    prepopulated_fields = {'slug': ('nome',)}
    search_fields = ('nome', 'paroquia__nome')
    fk_limitadas_por_paroquia = ()
    actions = ["ativar_servos", "desativar_servos", "abrir_inscricao_publica", "abrir_evento_servos"]

    fieldsets = (
        (None, {
            "fields": (
                "nome", "tipo", "paroquia",
                "data_inicio", "data_fim",
                "inicio_inscricoes", "fim_inscricoes",
                "valor_inscricao", "banner", "slug",
            )
        }),
        ("Vínculo / Servos", {
            "fields": ("evento_relacionado", "permitir_inscricao_servos"),
            "description": "Para eventos de Servos, selecione o evento principal. "
                           "No evento principal, use a flag para permitir inscrições de servos."
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        # Bloqueia edição manual do vínculo no principal
        if obj and obj.tipo != "servos":
            ro.append("evento_relacionado")
        return ro

    def servos_vinculado(self, obj):
        if obj.tipo == "servos":
            if obj.evento_relacionado:
                url = reverse("admin:inscricoes_eventoacampamento_change", args=[obj.evento_relacionado.pk])
                return format_html('<a href="{}">{} (principal)</a>', url, obj.evento_relacionado.nome)
            return "-"
        # principal: mostra o servos gerado automaticamente (se houver)
        ev = obj.servos_evento
        if not ev:
            return "-"
        url = reverse("admin:inscricoes_eventoacampamento_change", args=[ev.pk])
        return format_html('<a href="{}">{} (servos)</a>', url, ev.nome)
    servos_vinculado.short_description = "Vínculo"

    def status_servos(self, obj):
        """Mostra se o servos pode receber inscrição (considera flag + janela de datas do evento de servos)."""
        if obj.tipo == "servos":
            principal = obj.evento_relacionado
            if not principal:
                return "—"
            aceitar = principal.permitir_inscricao_servos
            hoje = timezone.localdate()
            janela = (obj.inicio_inscricoes <= hoje <= obj.fim_inscricoes)
            return "Abertas" if (aceitar and janela) else ("Fechadas" if aceitar else "Desabilitadas")
        # principal
        ev = obj.servos_evento
        if not ev:
            return "—"
        aceitar = obj.permitir_inscricao_servos
        hoje = timezone.localdate()
        janela = (ev.inicio_inscricoes <= hoje <= ev.fim_inscricoes)
        return "Abertas" if (aceitar and janela) else ("Fechadas" if aceitar else "Desabilitadas")
    status_servos.short_description = "Inscrições Servos"

    # Ações rápidas
    @admin.action(description="Ativar inscrições de Servos (nos principais selecionados)")
    def ativar_servos(self, request, queryset):
        count = 0
        for ev in queryset:
            if ev.tipo == "servos":
                # liga no principal
                if ev.evento_relacionado and not ev.evento_relacionado.permitir_inscricao_servos:
                    ev.evento_relacionado.permitir_inscricao_servos = True
                    ev.evento_relacionado.save(update_fields=["permitir_inscricao_servos"])
                    count += 1
            else:
                if not ev.permitir_inscricao_servos:
                    ev.permitir_inscricao_servos = True
                    ev.save(update_fields=["permitir_inscricao_servos"])
                    count += 1
        self.message_user(request, f"Inscrições de servos ativadas em {count} evento(s).", level=messages.SUCCESS)

    @admin.action(description="Desativar inscrições de Servos (nos principais selecionados)")
    def desativar_servos(self, request, queryset):
        count = 0
        for ev in queryset:
            if ev.tipo == "servos":
                if ev.evento_relacionado and ev.evento_relacionado.permitir_inscricao_servos:
                    ev.evento_relacionado.permitir_inscricao_servos = False
                    ev.evento_relacionado.save(update_fields=["permitir_inscricao_servos"])
                    count += 1
            else:
                if ev.permitir_inscricao_servos:
                    ev.permitir_inscricao_servos = False
                    ev.save(update_fields=["permitir_inscricao_servos"])
                    count += 1
        self.message_user(request, f"Inscrições de servos desativadas em {count} evento(s).", level=messages.SUCCESS)

    @admin.action(description="Abrir página pública de inscrição (nova aba)")
    def abrir_inscricao_publica(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Selecione apenas um evento.", level=messages.WARNING)
            return
        ev = queryset.first()
        try:
            url = ev.link_inscricao
            self.message_user(
                request,
                format_html('Abrir: <a href="{}" target="_blank" rel="noopener">/inscrição</a>', url),
                level=messages.INFO
            )
        except Exception:
            self.message_user(request, "Não foi possível montar a URL de inscrição.", level=messages.ERROR)

    @admin.action(description="Ir para o evento de Servos vinculado (se existir)")
    def abrir_evento_servos(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Selecione apenas um evento principal.", level=messages.WARNING)
            return
        ev = queryset.first()
        if ev.tipo == "servos":
            self.message_user(request, "Este já é o evento de servos.", level=messages.INFO)
            return
        servos = ev.servos_evento
        if not servos:
            self.message_user(request, "Ainda não há evento de servos vinculado.", level=messages.WARNING)
            return
        url = reverse("admin:inscricoes_eventoacampamento_change", args=[servos.pk])
        self.message_user(
            request,
            format_html('Abrir: <a href="{}">evento de servos</a>', url),
            level=messages.INFO
        )


# ======================= Filhos ========================
class FilhoInline(admin.StackedInline):
    model = Filho
    extra = 1
    fields = ("nome", "idade", "telefone", "endereco")
    show_change_link = True

@admin.register(Filho)
class FilhoAdmin(admin.ModelAdmin):
    list_display = ("nome", "idade", "telefone", "endereco", "inscricao_participante")
    search_fields = ("nome", "telefone", "inscricao__participante__nome")
    list_filter = ("idade",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs.select_related("inscricao__participante")
        if getattr(user, "paroquia_id", None):
            return qs.filter(inscricao__paroquia=user.paroquia).select_related("inscricao__participante")
        return qs.none()

    def inscricao_participante(self, obj):
        return obj.inscricao.participante.nome if obj.inscricao else "-"
    inscricao_participante.short_description = "Participante"


# ====================== Inscrições ======================
@admin.register(Inscricao)
class InscricaoAdmin(SomenteMinhaParoquiaAdmin):
    list_display = (
        "participante", "evento", "paroquia", "data_inscricao",
        "foi_selecionado", "pagamento_confirmado", "inscricao_concluida"
    )
    list_filter = ("evento__tipo", "evento", "paroquia", "foi_selecionado", "pagamento_confirmado")
    search_fields = ("participante__nome", "evento__nome", "paroquia__nome")
    fk_limitadas_por_paroquia = ("evento",)
    inlines = [FilhoInline]


# ======================= Pagamento ======================
@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ('inscricao', 'metodo', 'valor', 'status', 'data_pagamento', 'transacao_id')
    list_filter = ('status', 'metodo')
    search_fields = ('inscricao__participante__nome', 'transacao_id')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(inscricao__paroquia=user.paroquia)
        return qs.none()


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

class _BaseInscricaoTipoAdmin(SomenteMinhaParoquiaAdmin):
    list_display = BASE_LIST_DISPLAY
    list_filter = BASE_LIST_FILTER
    search_fields = BASE_SEARCH
    fk_limitadas_por_paroquia = ("inscricao",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user
        if (db_field.name == "inscricao"
            and not getattr(user, "is_superuser", False)
            and getattr(user, "tipo_usuario", "") != "admin_geral"
            and getattr(user, "paroquia_id", None)):
            kwargs["queryset"] = Inscricao.objects.filter(paroquia=user.paroquia)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(InscricaoSenior)
class InscricaoSeniorAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoJuvenil)
class InscricaoJuvenilAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoMirim)
class InscricaoMirimAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoServos)
class InscricaoServosAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoCasais)
class InscricaoCasaisAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoEvento)
class InscricaoEventoAdmin(_BaseInscricaoTipoAdmin): ...
@admin.register(InscricaoRetiro)
class InscricaoRetiroAdmin(_BaseInscricaoTipoAdmin): ...


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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(evento__paroquia=user.paroquia)
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "evento":
            user = request.user
            if (not getattr(user, "is_superuser", False)
                and getattr(user, "tipo_usuario", "") != "admin_geral"
                and getattr(user, "paroquia_id", None)):
                kwargs["queryset"] = EventoAcampamento.objects.filter(paroquia=user.paroquia)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(PastoralMovimento)
class PastoralMovimentoAdmin(admin.ModelAdmin):
    list_display = ['nome']
    search_fields = ['nome']


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'grau_parentesco', 'ja_e_campista', 'inscricao')
    search_fields = ('nome', 'telefone', 'grau_parentesco', 'inscricao__participante__nome')
    list_filter = ('ja_e_campista',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(inscricao__paroquia=user.paroquia)
        return qs.none()


@admin.register(Conjuge)
class ConjugeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'inscricao_participante', 'conjuge_inscrito', 'ja_e_campista')
    list_filter = ('conjuge_inscrito', 'ja_e_campista')
    search_fields = ('nome', 'inscricao__participante__nome', 'inscricao__participante__cpf')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(inscricao__paroquia=user.paroquia)
        return qs.none()

    def inscricao_participante(self, obj):
        return obj.inscricao.participante.nome
    inscricao_participante.short_description = 'Participante'


@admin.register(CrachaTemplate)
class CrachaTemplateAdmin(admin.ModelAdmin):
    list_display = ("nome",)


@admin.register(MercadoPagoConfig)
class MercadoPagoConfigAdmin(SomenteMinhaParoquiaAdmin):
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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(evento__paroquia=user.paroquia)
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "evento":
            user = request.user
            if (not getattr(user, "is_superuser", False)
                and getattr(user, "tipo_usuario", "") != "admin_geral"
                and getattr(user, "paroquia_id", None)):
                kwargs["queryset"] = EventoAcampamento.objects.filter(paroquia=user.paroquia)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MercadoPagoOwnerConfig)
class MercadoPagoOwnerConfigAdmin(admin.ModelAdmin):
    list_display = ("nome_exibicao", "ativo", "email_cobranca")
    search_fields = ("nome_exibicao", "email_cobranca")


@admin.register(Repasse)
class RepasseAdmin(admin.ModelAdmin):
    list_display = ("paroquia", "evento", "valor_repasse", "status", "criado_em")
    list_filter = ("status", "paroquia")
    search_fields = ("evento__nome", "paroquia__nome", "transacao_id")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
            return qs
        if getattr(user, "paroquia_id", None):
            return qs.filter(paroquia=user.paroquia)
        return qs.none()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user
        if db_field.name == "paroquia":
            if (not getattr(user, "is_superuser", False)
                and getattr(user, "tipo_usuario", "") != "admin_geral"
                and getattr(user, "paroquia_id", None)):
                kwargs["queryset"] = Paroquia.objects.filter(pk=user.paroquia_id)
        if db_field.name == "evento":
            if (not getattr(user, "is_superuser", False)
                and getattr(user, "tipo_usuario", "") != "admin_geral"
                and getattr(user, "paroquia_id", None)):
                kwargs["queryset"] = EventoAcampamento.objects.filter(paroquia=user.paroquia)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(SiteImage)
class SiteImageAdmin(admin.ModelAdmin):
    list_display = ("key", "categoria", "ativa", "preview", "updated_at")
    list_filter = ("categoria", "ativa")
    search_fields = ("key", "titulo", "alt_text", "legenda", "creditos")

    def preview(self, obj):
        try:
            url = obj.imagem.url
        except Exception:
            return "-"
        return format_html('<img src="{}" style="height:48px;border-radius:6px"/>', url)


@admin.register(LeadLanding)
class LeadLandingAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "whatsapp", "origem", "created_at", "ip")
    list_filter  = ("origem", "created_at")
    search_fields = ("nome", "email", "whatsapp", "mensagem")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ("path", "ip", "created_at")
    list_filter  = ("path", "created_at")
    search_fields = ("path", "ip", "user_agent")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


# ================== (Opcional) modelos de comunidade ==================
try:
    Comunicado = apps.get_model('inscricoes', 'Comunicado')
    class ComunicadoAdmin(SomenteMinhaParoquiaAdmin):
        list_display = ("titulo", "paroquia", "data_publicacao", "publicado")
        list_filter = ("publicado", "data_publicacao", "paroquia")
        search_fields = ("titulo", "texto")
    admin.site.register(Comunicado, ComunicadoAdmin)
except LookupError:
    pass

try:
    EventoComunitario = apps.get_model('inscricoes', 'EventoComunitario')
    class EventoComunitarioAdmin(SomenteMinhaParoquiaAdmin):
        list_display = ("nome", "paroquia", "data_inicio", "data_fim", "visivel_site")
        list_filter = ("visivel_site", "paroquia")
        search_fields = ("nome",)
        prepopulated_fields = {"slug": ("nome",)}
    admin.site.register(EventoComunitario, EventoComunitarioAdmin)
except LookupError:
    pass


def has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False

@admin.register(Grupo)
class GrupoAdmin(admin.ModelAdmin):
    # Base das colunas
    _cols = ["nome", "cor_preview"]
    if has_field(Grupo, "cor"):
        # Insere 'cor' logo após 'nome'
        _cols = ["nome", "cor", "cor_preview"]
    list_display = tuple(_cols)

    # Busca
    _search = ["nome"]
    if has_field(Grupo, "cor"):
        _search.append("cor")
    search_fields = tuple(_search)

    # Filtros
    _filters = []
    if has_field(Grupo, "cor"):
        _filters.append("cor")
    list_filter = tuple(_filters)

    def cor_preview(self, obj):
        """
        Quadradinho com a cor (quando for um HEX válido, ex.: #FF0000).
        Se não for hex, mostra um degradê neutro.
        """
        c = (getattr(obj, "cor", None) or "").strip()
        is_hex = c.startswith("#") and len(c) in (4, 7)
        css = c if is_hex else ""
        style = f"background:{css};" if css else "background:linear-gradient(45deg,#bbb,#ddd);"
        title = c or "—"
        return format_html(
            '<span title="{}" style="display:inline-block;width:1.2em;height:1.2em;'
            'border-radius:3px;border:1px solid #999;vertical-align:middle;{}"></span>',
            title, style
        )
    cor_preview.short_description = "Cor"

# ============ MINISTÉRIO (catálogo global) =============
@admin.register(Ministerio)
class MinisterioAdmin(admin.ModelAdmin):
    list_display = ("nome", "descricao_curta")
    search_fields = ("nome", "descricao")

    def descricao_curta(self, obj):
        return (obj.descricao[:60] + "…") if obj.descricao else "—"
    descricao_curta.short_description = "Descrição"


# ======== ALOCAÇÕES (ligadas à inscrição) =========
@admin.register(AlocacaoGrupo)
class AlocacaoGrupoAdmin(admin.ModelAdmin):
    list_display = ("inscricao", "evento_nome", "grupo", "cor_do_grupo")
    search_fields = (
        "inscricao__participante__nome",
        "inscricao__participante__cpf",
        "inscricao__evento__nome",
        "grupo__nome",
    )
    list_filter = ("inscricao__evento__paroquia", "inscricao__evento__tipo", "grupo__nome")
    raw_id_fields = ("inscricao",)
    autocomplete_fields = ("grupo",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("inscricao__participante", "inscricao__evento", "grupo")

    def evento_nome(self, obj):
        ev = getattr(obj.inscricao, "evento", None)
        return ev.nome if ev else "—"
    evento_nome.short_description = "Evento"

    def cor_do_grupo(self, obj):
        if not obj.grupo:
            return "—"
        c = (obj.grupo.cor or "").strip()
        is_hex = c.startswith("#") and (len(c) in (4, 7))
        css = c if is_hex else ""
        style = ("background:{};".format(css)) if css else "background:linear-gradient(45deg,#bbb,#ddd);"
        rotulo = getattr(obj.grupo, "nome", "Grupo")
        return format_html(
            '<span style="display:inline-block;width:1em;height:1em;'
            'border-radius:3px;border:1px solid #888;vertical-align:middle;{}"></span> {}',
            style, rotulo
        )
    cor_do_grupo.short_description = "Cor/Grupo"


@admin.register(AlocacaoMinisterio)
class AlocacaoMinisterioAdmin(admin.ModelAdmin):
    list_display = ("inscricao", "evento_nome", "ministerio", "is_coordenador", "funcao")
    search_fields = (
        "inscricao__participante__nome",
        "inscricao__participante__cpf",
        "inscricao__evento__nome",
        "ministerio__nome",
        "funcao",
    )
    list_filter = ("inscricao__evento__paroquia", "inscricao__evento__tipo", "ministerio__nome", "is_coordenador")
    raw_id_fields = ("inscricao",)
    autocomplete_fields = ("ministerio",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("inscricao__participante", "inscricao__evento", "ministerio")

    def evento_nome(self, obj):
        ev = getattr(obj.inscricao, "evento", None)
        return ev.nome if ev else "—"
    evento_nome.short_description = "Evento"


# ============ Inlines na Inscrição (1:1) ============
class AlocacaoGrupoInline(admin.StackedInline):
    model = AlocacaoGrupo
    extra = 0
    fields = ("grupo",)
    show_change_link = True
    autocomplete_fields = ("grupo",)

class AlocacaoMinisterioInline(admin.StackedInline):
    model = AlocacaoMinisterio
    extra = 0
    fields = ("ministerio", "funcao", "is_coordenador")
    show_change_link = True
    autocomplete_fields = ("ministerio",)

# ---- Anexa as inlines ao admin JÁ registrado de Inscricao (sem re-registrar) ----
if Inscricao in admin.site._registry:
    _admin_instance = admin.site._registry[Inscricao]
    current_inlines = list(getattr(_admin_instance, "inlines", []))  # pode ser tupla
    # evita duplicar se rodar mais de uma vez
    for inline in (AlocacaoGrupoInline, AlocacaoMinisterioInline):
        if inline not in current_inlines:
            current_inlines.append(inline)
    _admin_instance.inlines = current_inlines
else:
    # fallback: se por algum motivo ainda não estiver registrado, registra com as inlines
    @admin.register(Inscricao)
    class InscricaoAdmin(admin.ModelAdmin):
        list_display = ("participante", "evento", "status", "inscricao_enviada", "pagamento_confirmado")
        search_fields = ("participante__nome", "participante__cpf", "evento__nome")
        list_filter = ("evento__paroquia", "evento__tipo", "status")
        inlines = [AlocacaoGrupoInline, AlocacaoMinisterioInline]