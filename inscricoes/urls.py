from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.conf import settings
from .views import mp_config
from django.conf.urls.static import static
from .views import LoginComImagemView
from .views import (
    buscar_participante_ajax,
    iniciar_pagamento

)

app_name = 'inscricoes'  # importante para usar namespace

urlpatterns = [
    path("login/", LoginComImagemView.as_view(), name="login"),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('', views.home_redirect, name='home_redirect'),
    path('admin-geral/', views.admin_geral_home, name='admin_geral_home'),
    path('admin-geral/dashboard/', views.admin_geral_dashboard, name='admin_geral_dashboard'),

    path('admin-geral/paroquias/', views.admin_geral_list_paroquias, name='admin_geral_list_paroquias'),
    path('admin-geral/paroquias/criar/', views.admin_geral_create_paroquia, name='admin_geral_create_paroquia'),
    path('admin-geral/paroquias/<int:pk>/editar/', views.admin_geral_edit_paroquia, name='admin_geral_edit_paroquia'),
    path('admin-geral/paroquias/<int:pk>/deletar/', views.admin_geral_delete_paroquia, name='admin_geral_delete_paroquia'),

    path('admin-geral/usuarios/', views.admin_geral_list_usuarios, name='admin_geral_list_usuarios'),
    path('admin-geral/usuarios/criar/', views.admin_geral_create_usuario, name='admin_geral_create_usuario'),
    path('admin-geral/usuarios/<int:pk>/editar/', views.admin_geral_edit_usuario, name='admin_geral_edit_usuario'),
    path('admin-geral/usuarios/<int:pk>/deletar/', views.admin_geral_delete_usuario, name='admin_geral_delete_usuario'),
    path('admin-paroquia/', views.admin_paroquia_painel, name='admin_paroquia_painel'),

    path('eventos/novo/', views.evento_novo, name='evento_novo'),
    path('eventos/', views.eventos_listar, name='eventos_listar'),
    path('inscricoes/', views.inscricoes_listar, name='inscricoes_listar'),
    path('eventos/<uuid:pk>/editar/', views.evento_editar, name='evento_editar'),
    path('eventos/<uuid:pk>/deletar/', views.evento_deletar, name='evento_deletar'),
    path('admin-paroquia/evento/<uuid:evento_id>/participantes/', views.evento_participantes, name='evento_participantes'),
    path('inscricao/<int:pk>/', views.ver_inscricao, name='ver_inscricao'),
    path('inscricao/<slug:slug>/', views.inscricao_evento_publico, name='inscricao_evento_publico'),

    
    path('inscricao/<int:pk>/editar/', views.editar_inscricao, name='editar_inscricao'),
    path('inscricao/<int:pk>/deletar/', views.deletar_inscricao, name='deletar_inscricao'),
    path('inscricao/<int:pk>/ficha/', views.ficha_inscricao, name='ficha_inscricao'),
    path('inscricao/<int:pk>/imprimir-cracha/', views.imprimir_cracha, name='imprimir_cracha'),
    path('inscricao/<int:inscricao_id>/incluir-pagamento/', views.incluir_pagamento, name='incluir_pagamento'),
    path('evento/<slug:slug>/inscricao/', views.inscricao_inicial, name='inscricao_inicial'),
    path('formulario/<int:inscricao_id>/', views.formulario_personalizado, name='formulario_personalizado'),
    
    path('inscricao/', views.form_inscricao, name='form_inscricao'),
    path('cadastro/finalizado/<int:pk>/', views.inscricao_finalizada, name='inscricao_finalizada'),

    path('evento/<uuid:evento_id>/relatorio-crachas/', views.relatorio_crachas, name='relatorio_crachas'),
    path('evento/<uuid:evento_id>/relatorio-fichas-sorteio/', views.relatorio_fichas_sorteio, name='relatorio_fichas_sorteio'),
    path('evento/<uuid:evento_id>/relatorio-inscritos/', views.relatorio_inscritos, name='relatorio_inscritos'),
    path('evento/<uuid:evento_id>/relatorio-financeiro/', views.relatorio_financeiro, name='relatorio_financeiro'),

    path('evento/<slug:slug>/video/', views.pagina_video_evento, name='pagina_video_evento'),

    
    path('admin_geral/alterar_politica/', views.alterar_politica, name='alterar_politica'),

    path('evento/<uuid:evento_id>/relatorio_financeiro/', views.relatorio_financeiro, name='relatorio_financeiro'),

    path('formulario-contato/<int:inscricao_id>/', views.formulario_contato, name='formulario_contato'),
    path('formulario-saude/<int:inscricao_id>/', views.formulario_saude, name='formulario_saude'),

    path('ver-logs/', views.ver_logs_bruto, name='ver_logs'),
    path('ver-logs/lista/', views.ver_logs_lista, name='ver_logs_lista'),
    path('download-logs/', views.download_logs, name='download_logs'),


    path("evento/<slug:slug>/video/", views.pagina_video_evento, name="pagina_video_evento"),

    path('conta/alterar/<int:pk>/', views.alterar_credenciais, name='alterar_credenciais'),

    path('admin-geral/pastorais/', views.listar_pastorais_movimentos, name='listar_pastorais_movimentos'),
    path('admin-geral/pastorais/cadastrar/', views.cadastrar_pastoral_movimento, name='cadastrar_pastoral_movimento'),

    path('admin-geral/paroquia/<int:paroquia_id>/painel/', views.admin_paroquia_painel, name='admin_paroquia_painel'),

    path('evento/<uuid:evento_id>/verificar-selecao/',views.verificar_selecao,name='verificar_selecao'),

    path('ajax/buscar-participante/',buscar_participante_ajax,name='buscar_participante_ajax'),

    path('admin-paroquia/mp-config/',mp_config,name='mp_config'),

    path('inscricao/<int:inscricao_id>/pagar/',iniciar_pagamento,name='iniciar_pagamento'),
    path('api/mercadopago/webhook/', views.mp_webhook, name='mp_webhook'),

    path('contato-pagamento/', views.pagina_de_contato, name='pagina_de_contato'),

    path('evento/<uuid:evento_id>/imprimir-todas-fichas/',views.imprimir_todas_fichas,name='imprimir_todas_fichas'),

    path('evento/<uuid:evento_id>/relatorios/',views.relatorios_evento,name='relatorios_evento'),

    path('evento/<uuid:evento_id>/relatorios/',views.relatorios_evento,name='relatorios_evento'),
    path('evento/<uuid:evento_id>/relatorio/etiquetas-bagagem/',views.relatorio_etiquetas_bagagem,name='relatorio_etiquetas_bagagem'),
    path('evento/<uuid:evento_id>/relatorio/ficha-cozinha/',views.relatorio_ficha_cozinha,name='relatorio_ficha_cozinha'),
    path('evento/<uuid:evento_id>/relatorio/ficha-farmacia/',views.relatorio_ficha_farmacia,name='relatorio_ficha_farmacia'),
    path('qr/<str:token>.png', views.qr_code_png, name='qr_code_png'),

    path("pagamento/sucesso/<int:inscricao_id>/", views.mp_success, name="mp_success"),
    path("pagamento/pendente/<int:inscricao_id>/", views.mp_pending, name="mp_pending"),
    path("pagamento/falha/<int:inscricao_id>/",   views.mp_failure, name="mp_failure"),

    path("contato/", views.pagina_de_contato, name="pagina_de_contato"),

    path("pagamento/aguardando/<int:inscricao_id>/", views.aguardando_pagamento, name="aguardando_pagamento"),
    path("api/pagamento/status/<int:inscricao_id>/", views.status_pagamento, name="status_pagamento"),

    path("pagamento/pix/<int:inscricao_id>/", views.iniciar_pagamento_pix, name="iniciar_pagamento_pix"),
    path("api/pagamento/status/<int:inscricao_id>/", views.status_pagamento, name="status_pagamento"),  # se ainda não tiver
    path("pagamento/aguardando/<int:inscricao_id>/", views.aguardando_pagamento, name="aguardando_pagamento"),  # opcional: cartões

    path("minhas-inscricoes/", views.minhas_inscricoes_por_cpf, name="minhas_inscricoes_por_cpf"),
    path("minhas-inscricoes/", views.portal_participante, name="portal_participante"),

    path("admin-geral/financeiro/", views.financeiro_geral, name="financeiro_geral"),
    path("admin-geral/financeiro/exportar.csv", views.financeiro_geral_export, name="financeiro_geral_export"),

    path('admin-geral/paroquias/<int:pk>/status/',views.admin_geral_set_status_paroquia,name='admin_geral_set_status_paroquia'),

    path('paroquia/<int:paroquia_id>/toggle-status/', views.admin_geral_toggle_status_paroquia, name='admin_geral_toggle_status_paroquia'),

    path('evento/<uuid:evento_id>/politica-reembolso/',views.editar_politica_reembolso,name='editar_politica_reembolso'),

    path('admin-paroquia/usuarios/novo/', views.admin_paroquia_create_admin, name='admin_paroquia_create_admin'),
    path('admin-paroquia/usuarios/<int:user_id>/excluir/',views.admin_paroquia_delete_admin,name='admin_paroquia_delete_admin'),

    path('ajax/buscar-conjuge/', views.ajax_buscar_conjuge, name='ajax_buscar_conjuge'),

    path("admin-paroquia/financeiro/repasses/", views.repasse_lista_eventos, name="repasse_lista_eventos"),
    path("admin-paroquia/financeiro/repasse/<uuid:evento_id>/", views.repasse_evento_detalhe, name="repasse_evento_detalhe"),
    path("admin-paroquia/financeiro/repasse/<uuid:evento_id>/gerar-pix/", views.gerar_pix_repasse_evento, name="gerar_pix_repasse_evento"),
    path("webhooks/mp-owner/", views.mp_owner_webhook, name="mp_owner_webhook"),
    path("eventos/<slug:slug>/video/", views.video_evento_form, name="video_evento_form"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
