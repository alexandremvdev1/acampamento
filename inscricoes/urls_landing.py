from django.urls import path
from .views_landing import landing_view, contato_enviar

app_name = "landing"
urlpatterns = [
    path("", landing_view, name="landing"),
    path("contato/enviar", contato_enviar, name="contato_enviar"),
]
