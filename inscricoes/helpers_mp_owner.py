# helpers_mp_owner.py
from .models import MercadoPagoOwnerConfig
import mercadopago

def mp_owner_client():
    cfg = MercadoPagoOwnerConfig.objects.filter(ativo=True).first()
    if not cfg or not cfg.access_token:
        raise RuntimeError("Mercado Pago do DONO não está configurado/ativo.")
    return mercadopago.SDK(cfg.access_token), cfg
