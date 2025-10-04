# inscricoes/management/commands/where_is_db.py
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings

class Command(BaseCommand):
    help = "Mostra para qual banco o Django está conectado (host, db, user, ssl, etc.)."

    def handle(self, *args, **kwargs):
        cfg = connection.settings_dict.copy()
        # Não exibir senha
        cfg.pop("PASSWORD", None)
        self.stdout.write(self.style.MIGRATE_HEADING("==> DATABASE SETTINGS (default)"))
        for k in ["ENGINE","HOST","PORT","NAME","USER","OPTIONS","CONN_MAX_AGE"]:
            self.stdout.write(f"{k}: {cfg.get(k)}")
        self.stdout.write(self.style.SUCCESS("\nDica: rode também 'python manage.py check_counts' para ver se os dados estão aqui."))
