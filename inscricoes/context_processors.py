from typing import Optional
from django.core.cache import cache
from django.utils.functional import cached_property

from .models import PoliticaPrivacidade  # ajuste o import conforme seu app

CACHE_KEY = "ctx_politica_global"
CACHE_TTL = 300  # 5 minutos

def _sanitize_wa(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    # Remove "+" e espaços p/ wa.me
    return phone.replace("+", "").replace(" ", "")

def politica_context(request):
    """
    Disponibiliza 'politica' e atalhos:
      - suporte_email
      - suporte_phone_display
      - suporte_whatsapp_link (pronto pra usar)
    Tenta por paróquia do usuário; se não houver, cai no primeiro registro.
    """
    # cache para evitar query a cada request
    data = cache.get(CACHE_KEY)
    if data is not None:
        return data

    politica = None

    # Tenta por paróquia, se o modelo tiver FK 'paroquia'
    try:
        has_paroquia_fk = any(f.name == "paroquia" for f in PoliticaPrivacidade._meta.get_fields())
    except Exception:
        has_paroquia_fk = False

    user_paroquia = getattr(getattr(request, "user", None), "paroquia", None)

    try:
        if has_paroquia_fk and user_paroquia:
            politica = PoliticaPrivacidade.objects.filter(paroquia=user_paroquia).first()
        if not politica:
            politica = PoliticaPrivacidade.objects.first()
    except Exception:
        politica = None

    suporte_email = getattr(politica, "email_contato", None) if politica else None
    suporte_phone_display = getattr(politica, "telefone_contato", None) if politica else None
    suporte_whatsapp_link = f"https://wa.me/{_sanitize_wa(suporte_phone_display)}" if suporte_phone_display else None

    ctx = {
        "politica": politica,
        "suporte_email": suporte_email,
        "suporte_phone_display": suporte_phone_display,
        "suporte_whatsapp_link": suporte_whatsapp_link,
    }
    cache.set(CACHE_KEY, ctx, CACHE_TTL)
    return ctx
