from django.urls import path, register_converter
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

from . import views
from .views import (
    LoginComImagemView,
    mp_config,
    buscar_participante_ajax,
    iniciar_pagamento,
)

# ========= Conversor que aceita int OU UUID =========
import uuid

class IntOrUUIDConverter:
    regex = r"[0-9]+|[0-9a-fA-F-]{36}"
    def to_python(self, value):
        try:
            return uuid.UUID(str(value))
        except Exception:
            return int(value)
    def to_url(self, value):
        return str(value)

register_converter(IntOrUUIDConverter, "iduu")
# ====================================================

app_name = "inscricoes"

urlpatterns = [
    # Auth / Home
    path("login/", LoginComImagemView.as_view(), name="login"),
    path("entrar/", LoginComImagemView.as_view(), name="entrar"),  # atalho opcional
    path("logout/", auth_views.LogoutView.as_view(next_page="inscricoes:login"), name="logout"),

    # AGORA o / vai pro redirect (painel p/ admins ou login)
    path("", views.home_redirect, name="home_redirect"),

    # Landing “marketing” fica só aqui (não mais em "/")
    path("site/", views.landing, name="landing"),
    path("site/contato/enviar", views.contato_enviar, name="contato_enviar"),
    path("site/contato-enviar/", views.contato_enviar, name="contato_enviar"),

    # Admin Geral
    path("admin-geral/", views.admin_geral_home, name="admin_geral_home"),
    path("admin-geral/dashboard/", views.admin_geral_dashboard, name="admin_geral_dashboard"),

    path("admin-geral/paroquias/", views.admin_geral_list_paroquias, name="admin_geral_list_paroquias"),
    path("admin-geral/paroquias/criar/", views.admin_geral_create_paroquia, name="admin_geral_create_paroquia"),
    path("admin-geral/paroquias/<int:pk>/editar/", views.admin_geral_edit_paroquia, name="admin_geral_edit_paroquia"),
    path("admin-geral/paroquias/<int:pk>/deletar/", views.admin_geral_delete_paroquia, name="admin_geral_delete_paroquia"),
    path("admin-geral/paroquias/<int:pk>/status/", views.admin_geral_set_status_paroquia, name="admin_geral_set_status_paroquia"),
    path("paroquia/<int:paroquia_id>/toggle-status/", views.admin_geral_toggle_status_paroquia, name="admin_geral_toggle_status_paroquia"),

    path("admin-geral/usuarios/", views.admin_geral_list_usuarios, name="admin_geral_list_usuarios"),
    path("admin-geral/usuarios/criar/", views.admin_geral_create_usuario, name="admin_geral_create_usuario"),
    path("admin-geral/usuarios/<int:pk>/editar/", views.admin_geral_edit_usuario, name="admin_geral_edit_usuario"),
    path("admin-geral/usuarios/<int:pk>/deletar/", views.admin_geral_delete_usuario, name="admin_geral_delete_usuario"),

    path("admin-geral/financeiro/", views.financeiro_geral, name="financeiro_geral"),
    path("admin-geral/financeiro/exportar.csv", views.financeiro_geral_export, name="financeiro_geral_export"),

    path("admin-geral/pastorais/", views.listar_pastorais_movimentos, name="listar_pastorais_movimentos"),
    path("admin-geral/pastorais/cadastrar/", views.cadastrar_pastoral_movimento, name="cadastrar_pastoral_movimento"),

    # Admin Paróquia (painel)
    path("admin-paroquia/", views.admin_paroquia_painel, name="admin_paroquia_painel"),
    path("admin-geral/paroquia/<int:paroquia_id>/painel/", views.admin_paroquia_painel, name="admin_paroquia_painel"),
    path("admin-paroquia/usuarios/novo/", views.admin_paroquia_create_admin, name="admin_paroquia_create_admin"),
    path("admin-paroquia/usuarios/<int:user_id>/excluir/", views.admin_paroquia_delete_admin, name="admin_paroquia_delete_admin"),

    # Eventos - listagem por paróquia no admin geral
    path("admin-geral/paroquia/<int:pk>/eventos/", views.admin_paroquia_eventos, name="admin_paroquia_eventos"),

    # Eventos (CRUD e ajustes)
    path("eventos/", views.eventos_listar, name="eventos_listar"),
    path("eventos/novo/", views.evento_novo, name="evento_novo"),
    path("eventos/<uuid:pk>/editar/", views.evento_editar, name="evento_editar"),
    path("eventos/<uuid:pk>/deletar/", views.evento_deletar, name="evento_deletar"),
    path("evento/<uuid:pk>/toggle-servos/", views.evento_toggle_servos, name="evento_toggle_servos"),
    path("eventos/<uuid:evento_id>/configuracoes/", views.evento_configuracoes, name="evento_configuracoes"),

    # Participantes do evento
    path("admin-paroquia/evento/<uuid:evento_id>/participantes/", views.evento_participantes, name="evento_participantes"),
    path("evento/<uuid:evento_id>/alocar-massa/", views.alocar_em_massa, name="alocar_em_massa"),

    # Relatórios do evento
    path("evento/<uuid:evento_id>/relatorios/", views.relatorios_evento, name="relatorios_evento"),
    path("evento/<uuid:evento_id>/relatorio-crachas/", views.relatorio_crachas, name="relatorio_crachas"),
    path("evento/<uuid:evento_id>/relatorio-fichas-sorteio/", views.relatorio_fichas_sorteio, name="relatorio_fichas_sorteio"),
    path("evento/<uuid:evento_id>/relatorio-inscritos/", views.relatorio_inscritos, name="relatorio_inscritos"),
    path("evento/<uuid:evento_id>/relatorio-financeiro/", views.relatorio_financeiro, name="relatorio_financeiro"),
    path("evento/<uuid:evento_id>/relatorio_financeiro/", views.relatorio_financeiro, name="relatorio_financeiro_compat"),

    # Financeiro / repasses (admin paróquia)
    path("admin-paroquia/financeiro/repasses/", views.repasse_lista_eventos, name="repasse_lista_eventos"),
    path("admin-paroquia/financeiro/repasse/<uuid:evento_id>/", views.repasse_evento_detalhe, name="repasse_evento_detalhe"),
    path("admin-paroquia/financeiro/repasse/<uuid:evento_id>/gerar-pix/", views.gerar_pix_repasse_evento, name="gerar_pix_repasse_evento"),

    # Inscrição (público e administrativo)
    path("evento/<slug:slug>/inscricao/", views.inscricao_inicial, name="inscricao_inicial"),
    path("inscricao/<int:pk>/", views.ver_inscricao, name="ver_inscricao"),
    path("inscricao/<slug:slug>/", views.inscricao_evento_publico, name="inscricao_evento_publico"),
    path("inscricao/<int:pk>/editar/", views.editar_inscricao, name="editar_inscricao"),
    path("inscricao/<int:pk>/deletar/", views.deletar_inscricao, name="deletar_inscricao"),
    path("inscricao/<int:pk>/ficha/", views.ficha_inscricao, name="ficha_inscricao"),
    path("inscricao/<int:pk>/imprimir-cracha/", views.imprimir_cracha, name="imprimir_cracha"),
    path("inscricao/<int:pk>/ficha-geral/", views.inscricao_ficha_geral, name="inscricao_ficha_geral"),
    path("inscricao/<int:pk>/toggle-selecao/", views.toggle_selecao_inscricao, name="toggle_selecao_inscricao"),

    # Alocações (individual)
    path("inscricao/<int:inscricao_id>/alocar-ministerio/", views.alocar_ministerio, name="alocar_ministerio"),
    path("inscricao/<int:inscricao_id>/alocar-grupo/", views.alocar_grupo, name="alocar_grupo"),

    # Ministérios
    path("paroquia/<int:paroquia_id>/ministerios/", views.ministerios_home, name="ministerios_home"),
    path("ministerios/evento/<iduu:evento_id>/", views.ministerios_evento, name="ministerios_evento"),
    path("ministerios/evento/<iduu:evento_id>/novo/", views.ministerio_create, name="ministerio_create"),
    path("ministerio/<int:pk>/excluir/", views.excluir_ministerio, name="excluir_ministerio"),
    path("ministerios/evento/<uuid:evento_id>/novo/",views.ministerio_novo,name="ministerio_novo",),
    path(
        "ministerios/evento/<uuid:evento_id>/",
        views.ministerios_evento,
        name="ministerios_evento",
    ),
    path(
        "ministerios/<int:pk>/alocacoes/",
        views.alocacoes_ministerio,
        name="alocacoes_ministerio",
    ),
    path(
        "ministerios/<int:pk>/editar/",
        views.ministerio_editar,
        name="ministerio_editar",
    ),
    path(
        "ministerios/<int:pk>/excluir/",
        views.excluir_ministerio,
        name="ministerio_deletar",   # seu template já usa esse name
    ),

    path("ministerios/<int:pk>/alocar/", views.alocar_inscricao_ministerio, name="alocar_inscricao_ministerio"),
    path("ministerios/alocacao/<int:alocacao_id>/remover/", views.desalocar_inscricao_ministerio, name="desalocar_inscricao_ministerio"),
    path("ministerios/alocacao/<int:alocacao_id>/coordenador/", views.toggle_coordenador_ministerio, name="toggle_coordenador_ministerio"),
    # Formulários complementares
    path("formulario/casais/<uuid:evento_id>/", views.formulario_casais, name="formulario_casais"),
    path("formulario/<int:inscricao_id>/", views.formulario_personalizado, name="formulario_personalizado"),
    path("formulario-contato/<int:inscricao_id>/", views.formulario_contato, name="formulario_contato"),
    path("formulario-saude/<int:inscricao_id>/", views.formulario_saude, name="formulario_saude"),

    # Pagamentos (MP)
    path("inscricao/<int:inscricao_id>/pagar/", iniciar_pagamento, name="iniciar_pagamento"),
    path("pagamento/pix/<int:inscricao_id>/", views.iniciar_pagamento_pix, name="iniciar_pagamento_pix"),
    path("pagamento/aguardando/<int:inscricao_id>/", views.aguardando_pagamento, name="aguardando_pagamento"),
    path("api/pagamento/status/<int:inscricao_id>/", views.status_pagamento, name="status_pagamento"),
    path("api/mercadopago/webhook/", views.mp_webhook, name="mp_webhook"),
    path("webhooks/mp-owner/", views.mp_owner_webhook, name="mp_owner_webhook"),
    path("pagamento/sucesso/<int:inscricao_id>/", views.mp_success, name="mp_success"),
    path("pagamento/pendente/<int:inscricao_id>/", views.mp_pending, name="mp_pending"),
    path("pagamento/falha/<int:inscricao_id>/", views.mp_failure, name="mp_failure"),
    path("admin-paroquia/mp-config/", mp_config, name="mp_config"),
    path("inscricao/<int:inscricao_id>/incluir-pagamento/",views.incluir_pagamento,name="incluir_pagamento",),

    # Portal do participante
    path("minhas-inscricoes/", views.minhas_inscricoes_por_cpf, name="minhas_inscricoes_por_cpf"),

    # Vídeo do evento / Telão
    path("evento/<slug:slug>/video/", views.pagina_video_evento, name="pagina_video_evento"),
    path("eventos/<slug:slug>/video/", views.video_evento_form, name="video_evento_form"),
    path("telão/<slug:slug>/", views.painel_sorteio, name="painel_sorteio"),
    path("api/evento/<slug:slug>/selecionados/", views.api_selecionados, name="api_selecionados"),

    # Relatórios extras
    path("evento/<uuid:evento_id>/imprimir-todas-fichas/", views.imprimir_todas_fichas, name="imprimir_todas_fichas"),
    path("evento/<uuid:evento_id>/relatorio/etiquetas-bagagem/", views.relatorio_etiquetas_bagagem, name="relatorio_etiquetas_bagagem"),
    path("evento/<uuid:evento_id>/relatorio/ficha-cozinha/", views.relatorio_ficha_cozinha, name="relatorio_ficha_cozinha"),
    path("evento/<uuid:evento_id>/relatorio/ficha-farmacia/", views.relatorio_ficha_farmacia, name="relatorio_ficha_farmacia"),

    # Utils
    path("qr/<str:token>.png", views.qr_code_png, name="qr_code_png"),
    path("ajax/buscar-participante/", buscar_participante_ajax, name="buscar_participante_ajax"),
    path("ajax/buscar-conjuge/", views.ajax_buscar_conjuge, name="ajax_buscar_conjuge"),
    path("evento/<uuid:evento_id>/verificar-selecao/", views.verificar_selecao, name="verificar_selecao"),
    path("conta/alterar/<int:pk>/", views.alterar_credenciais, name="alterar_credenciais"),
    path("admin_geral/alterar_politica/", views.alterar_politica, name="alterar_politica"),
    path("evento/<uuid:evento_id>/politica-reembolso/", views.editar_politica_reembolso, name="editar_politica_reembolso"),

    # Logs
    path("ver-logs/", views.ver_logs_bruto, name="ver_logs"),
    path("ver-logs/lista/", views.ver_logs_lista, name="ver_logs_lista"),
    path("download-logs/", views.download_logs, name="download_logs"),

    # Publicações
    path("painel/publicacoes/", views.publicacoes_list, name="publicacoes_list"),
    path("painel/publicacoes/nova/", views.publicacao_criar, name="publicacao_criar"),
    path("painel/publicacoes/<int:pk>/editar/", views.publicacao_editar, name="publicacao_editar"),
    path("painel/publicacoes/<int:pk>/excluir/", views.publicacao_excluir, name="publicacao_excluir"),

    # Outras páginas
    path("contribuicao/", TemplateView.as_view(template_name="inscricoes/contribuicao.html"), name="contribuicao"),
    path("comunicado/<int:pk>/", views.comunicado_detalhe, name="comunicado_detalhe"),
    path("contato/", views.pagina_de_contato, name="pagina_de_contato"),

    path("admin-geral/paroquia/<int:paroquia_id>/toggle-status/", views.admin_geral_toggle_status_paroquia, name="admin_geral_toggle_status_paroquia"),

    path("inscricao/<int:inscricao_id>/alterar-status/", views.alterar_status_inscricao, name="alterar_status_inscricao"),
    path("admin-paroquia/acoes/", views.admin_paroquia_acoes, name="admin_paroquia_acoes"),
    path("admin-paroquia/acoes/<int:paroquia_id>/", views.admin_paroquia_acoes, name="admin_paroquia_acoes_por_paroquia"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
