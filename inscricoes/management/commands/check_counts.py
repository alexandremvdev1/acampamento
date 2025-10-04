# inscricoes/management/commands/check_counts.py
from django.core.management.base import BaseCommand
from django.db.models import Count
from inscricoes.models import (
    Paroquia, EventoAcampamento, Participante, Inscricao, Pagamento, Repasse,
)

class Command(BaseCommand):
    help = "Mostra contagens básicas para confirmar se os dados do seed estão neste banco."

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING("==> COUNTS"))
        self.stdout.write(f"Paróquias: {Paroquia.objects.count()}")
        self.stdout.write(f"Eventos:   {EventoAcampamento.objects.count()}")
        self.stdout.write(f"Particip.: {Participante.objects.count()}")
        self.stdout.write(f"Inscrições:{Inscricao.objects.count()}")
        self.stdout.write(f"Pagamentos:{Pagamento.objects.count()}")
        self.stdout.write(f"Repasses:  {Repasse.objects.count()}")

        self.stdout.write(self.style.MIGRATE_HEADING("\n==> Eventos por tipo"))
        tipos = (EventoAcampamento.objects
                 .values("tipo")
                 .annotate(total=Count("id"))
                 .order_by("tipo"))
        for t in tipos:
            self.stdout.write(f"{t['tipo']}: {t['total']}")
