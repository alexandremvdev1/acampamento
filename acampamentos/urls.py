from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from inscricoes.views import whatsapp_webhook

urlpatterns = [
    path('admin/', admin.site.urls),

    # Suas URLs do app 'inscricoes'
    path('', include('inscricoes.urls', namespace='inscricoes')),
    

    # Substitui o login padrão para usar seu template personalizado
    path('accounts/login/', auth_views.LoginView.as_view(template_name='inscricoes/login.html'), name='login'),

    # Inclui as demais URLs de autenticação (logout, password_change etc),
    # mas omitindo a url padrão de login para evitar conflito
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='inscricoes:login'), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path("webhooks/whatsapp/", whatsapp_webhook, name="whatsapp_webhook"),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
