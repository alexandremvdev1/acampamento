from django.utils import timezone
from ..models import PreferenciasComunicacao

def registrar_optin_marketing(participante, request=None, versao='v1'):
    prefs, _ = PreferenciasComunicacao.objects.get_or_create(participante=participante)
    prova = None
    if request:
        ip = request.META.get('REMOTE_ADDR')
        ua = request.META.get('HTTP_USER_AGENT')
        prova = f"IP={ip} | UA={ua} | ts={timezone.now().isoformat()}"
    prefs.marcar_optin_marketing(fonte='form', prova=prova, versao=versao)
