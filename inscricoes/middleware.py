# inscricoes/middleware.py
import logging
from datetime import datetime
from django.utils.deprecation import MiddlewareMixin


logger = logging.getLogger('django')


class UserActivityLoggingMiddleware(MiddlewareMixin):
    """
    Loga acessos de usuários AUTENTICADOS no formato:
    2025-08-30 17:28:00.798 | <username> acessou GET /site/contato/enviar — 200 45ms (ip=127.0.0.1)
    """
    EXCLUDE_PREFIXES = ('/static', '/media', '/__debug__', '/admin')  # evita ruído

    def process_request(self, request):
        # marca o início pra medir o tempo de resposta
        request._ua_start = datetime.now()

    def process_response(self, request, response):
        try:
            path = getattr(request, "path", "/") or "/"
            if any(path.startswith(p) for p in self.EXCLUDE_PREFIXES):
                return response

            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                # duração
                dur_ms = None
                try:
                    dur_ms = int((datetime.now() - getattr(request, "_ua_start")).total_seconds() * 1000)
                except Exception:
                    pass

                # dados úteis
                ip = request.META.get('REMOTE_ADDR')
                method = getattr(request, "method", "GET")
                status = getattr(response, "status_code", "-")

                # log no logger 'django' (como você pediu)
                logger.info(
                    "%s | %s acessou %s %s — %s %s%s",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    user.username,
                    method,
                    path,
                    status,
                    f"{dur_ms}ms " if dur_ms is not None else "",
                    f"(ip={ip})" if ip else "",
                )
        except Exception:
            # logging nunca deve derrubar a request
            pass

        return response

