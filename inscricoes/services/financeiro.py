from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
from django.utils import timezone

from ..models import Pagamento, Repasse, RepasseItem

CENT = Decimal("0.01")
def _round(v: Decimal) -> Decimal:
    return (v or Decimal("0.00")).quantize(CENT, rounding=ROUND_HALF_UP)

def _liq_pagto(p: Pagamento) -> Decimal:
    if p.net_received and p.net_received > 0:
        return _round(p.net_received)
    bruto = p.valor or Decimal("0.00")
    fee   = p.fee_mp or Decimal("0.00")
    liq = bruto - fee
    return _round(liq if liq > 0 else Decimal("0.00"))

def _percentual(paroquia, evento, override: Decimal | None) -> Decimal:
    if override is not None:
        return _round(override)
    ev_perc = getattr(evento, "repasse_percentual_override", None)
    if ev_perc is not None:
        return _round(ev_perc)
    return _round(getattr(paroquia, "repasse_percentual", Decimal("0.00")))

def financeiro_evento(paroquia, evento, *, percentual_override: Decimal | None = None) -> dict:
    """
    Retorna um dicionário com todos os números para o relatório financeiro do evento.
    - Considera SOMENTE pagamentos confirmados.
    - Usa net_received como líquido; senão valor - fee_mp.
    - Calcula repasse previsto (com param/override/padrão).
    - Mostra também repasses já gerados (pendente) e pagos.
    """
    # --- pagamentos confirmados do evento/paróquia
    pagamentos = (
        Pagamento.objects
        .filter(
            inscricao__evento=evento,
            inscricao__paroquia=paroquia,
            status=Pagamento.StatusPagamento.CONFIRMADO,
        )
        .select_related("inscricao")
    )

    qtd_confirmados = pagamentos.count()
    bruto_total = _round(sum([(p.valor or Decimal("0.00")) for p in pagamentos], Decimal("0.00")))
    taxas_total = _round(sum([(p.fee_mp or Decimal("0.00")) for p in pagamentos], Decimal("0.00")))
    liquido_total = _round(sum([_liq_pagto(p) for p in pagamentos], Decimal("0.00")))

    # --- percentual que será exibido (param > evento > paróquia)
    perc = _percentual(paroquia, evento, percentual_override)

    # --- repasse previsto (sobre o líquido)
    repasse_previsto = _round(liquido_total * (perc / Decimal("100")))

    # --- repasses (gerados)
    repasses_pend = Repasse.objects.filter(paroquia=paroquia, evento=evento, status=Repasse.Status.PENDENTE)
    repasses_pago = Repasse.objects.filter(paroquia=paroquia, evento=evento, status=Repasse.Status.PAGO)

    pend_base = repasses_pend.aggregate(s=Sum("valor_base"))["s"] or Decimal("0.00")
    pend_val  = repasses_pend.aggregate(s=Sum("valor_repasse"))["s"] or Decimal("0.00")

    pago_base = repasses_pago.aggregate(s=Sum("valor_base"))["s"] or Decimal("0.00")
    pago_val  = repasses_pago.aggregate(s=Sum("valor_repasse"))["s"] or Decimal("0.00")

    pend_base = _round(pend_base); pend_val = _round(pend_val)
    pago_base = _round(pago_base); pago_val = _round(pago_val)

    # --- líquido para a paróquia (após repasse previsto)
    liquido_pos_repasse_previsto = _round(liquido_total - repasse_previsto)
    # também exibir versões “considerando já gerado/pago” (útil na prática)
    liquido_pos_repasse_pendente = _round(liquido_total - pend_val)
    liquido_pos_repasse_pago     = _round(liquido_total - pago_val)

    return {
        "agora": timezone.localtime(),
        "evento": evento,
        "paroquia": paroquia,

        "qtd_confirmados": qtd_confirmados,
        "bruto_total": bruto_total,
        "taxas_total": taxas_total,
        "liquido_total": liquido_total,

        "percentual_usado": perc,
        "repasse_previsto": repasse_previsto,

        "repasses_pendentes": repasses_pend,
        "repasses_pagos": repasses_pago,

        "pend_base": pend_base, "pend_val": pend_val,
        "pago_base": pago_base, "pago_val": pago_val,

        "liquido_pos_repasse_previsto": liquido_pos_repasse_previsto,
        "liquido_pos_repasse_pendente": liquido_pos_repasse_pendente,
        "liquido_pos_repasse_pago": liquido_pos_repasse_pago,
    }
