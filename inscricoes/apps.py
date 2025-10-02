# inscricoes/apps.py
from django.apps import AppConfig

class InscricoesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inscricoes"

    def ready(self) -> None:
        # Importa os signals para registrar os receivers
        from . import signals  # noqa: F401
