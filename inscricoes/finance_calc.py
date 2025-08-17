# finance_calc.py
from decimal import Decimal
from django.db.models import Sum
from .models import Pagamento

TAXA_SISTEMA_DEFAULT = Decimal("3.00")

def calcular_financeiro_evento(evento, taxa_percentual=TAXA_SISTEMA_DEFAULT):
    pagos = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO
    )
    bruto = pagos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
    taxas_mp = pagos.aggregate(total=Sum("fee_mp"))["total"] or Decimal("0.00")  # precisa salvar fee_mp no webhook
    base = (bruto - taxas_mp).quantize(Decimal("0.01"))
    taxa = (base * Decimal(taxa_percentual) / Decimal("100")).quantize(Decimal("0.01"))
    liquido_paroquia = (base - taxa).quantize(Decimal("0.01"))

    return {
        "bruto": bruto,
        "taxas_mp": taxas_mp,
        "base_repasse": base,
        "taxa_percent": Decimal(taxa_percentual),
        "valor_repasse": taxa,
        "liquido_paroquia": liquido_paroquia,
    }
