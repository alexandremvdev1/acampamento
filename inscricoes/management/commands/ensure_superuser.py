# inscricoes/management/commands/ensure_superuser.py
import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction

class Command(BaseCommand):
    help = "Cria/atualiza um superuser a partir de variáveis de ambiente, idempotente."

    def handle(self, *args, **options):
        User = get_user_model()

        username_field = User.USERNAME_FIELD
        identifier = (
            os.environ.get("DJANGO_SUPERUSER_IDENTIFIER")
            or os.environ.get("DJANGO_SUPERUSER_USERNAME")
            or os.environ.get("DJANGO_SUPERUSER_EMAIL")
        )
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL") or "admin@example.com"
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not identifier:
            self.stderr.write(self.style.ERROR(
                "Defina DJANGO_SUPERUSER_IDENTIFIER (ou DJANGO_SUPERUSER_USERNAME/EMAIL)."
            ))
            return

        if not password:
            self.stderr.write(self.style.ERROR("Defina DJANGO_SUPERUSER_PASSWORD."))
            return

        defaults = {}
        # Preenche o campo email se existir no model
        if hasattr(User, "email"):
            defaults["email"] = email

        with transaction.atomic():
            user, created = User.objects.get_or_create(
                **{username_field: identifier},
                defaults=defaults,
            )

            changed = False

            # Garante flags de superuser/staff
            if not user.is_superuser or not user.is_staff:
                user.is_superuser = True
                user.is_staff = True
                changed = True

            # Atualiza email se veio por env e o model tiver o campo
            if hasattr(user, "email") and email and user.email != email:
                user.email = email
                changed = True

            # Atualiza a senha somente se a flag estiver habilitada ou se acabou de criar
            update_pwd = os.environ.get("DJANGO_SUPERUSER_UPDATE_PASSWORD", "false").lower() in ("1", "true", "yes")
            if created or update_pwd:
                user.set_password(password)
                changed = True

            if changed:
                user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{identifier}' criado."))
        else:
            self.stdout.write(self.style.WARNING(
                f"Superuser '{identifier}' já existia; {'atualizado' if changed else 'sem alterações'}."
            ))
