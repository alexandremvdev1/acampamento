# inscricoes/management/commands/create_admin.py
import os
from django.db import transaction
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Cria/atualiza um superusuário de forma idempotente (útil p/ Neon/CI)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.getenv("DJANGO_SUPERUSER_USERNAME", "admin"))
        parser.add_argument("--email", default=os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@example.com"))
        parser.add_argument("--password", default=os.getenv("DJANGO_SUPERUSER_PASSWORD"))
        parser.add_argument("--update-password", action="store_true",
                            help="Atualiza a senha se o usuário já existir.")

    @transaction.atomic
    def handle(self, *args, **opts):
        User = get_user_model()
        username = (opts["username"] or "").strip()
        email = (opts["email"] or "").strip().lower()
        password = opts["password"]

        if not username or not email:
            raise CommandError("Informe --username e --email ou use DJANGO_SUPERUSER_USERNAME/EMAIL.")

        try:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": email, "is_staff": True, "is_superuser": True, "is_active": True},
            )

            if created:
                if not password:
                    raise CommandError("Defina --password (ou DJANGO_SUPERUSER_PASSWORD) no primeiro create.")
                user.set_password(password)
                if user.email != email:
                    user.email = email
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✅ Superusuário criado: {username} <{email}>"))
                return

            changed = False
            if user.email != email:
                user.email = email
                changed = True

            if opts["update_password"]:
                if not password:
                    raise CommandError("Use --password com --update-password.")
                user.set_password(password)
                changed = True

            flags = []
            if not user.is_staff:
                user.is_staff = True; flags.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True; flags.append("is_superuser")
            if not user.is_active:
                user.is_active = True; flags.append("is_active")
            changed = changed or bool(flags)

            if changed:
                user.save()
                quais = ", ".join(flags) if flags else "email/senha"
                self.stdout.write(self.style.SUCCESS(
                    f"♻️ Superusuário atualizado: {username} <{email}> (alterações: {quais})"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"ℹ️ Já existe e está OK: {username} <{email}> (nada a fazer)"
                ))

        except Exception as e:
            raise CommandError(f"Falha ao criar/atualizar superusuário: {e}")
