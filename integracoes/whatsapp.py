# integracoes/whatsapp.py
import requests
from django.conf import settings

WHATSAPP_TOKEN = getattr(settings, "WHATSAPP_TOKEN")
PHONE_NUMBER_ID = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID")
API_VERSION = getattr(settings, "WHATSAPP_API_VERSION", "v20.0")

BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}

def send_text(to_e164: str, body: str) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"body": body},
    }
    r = requests.post(BASE_URL, json=payload, headers=HEADERS, timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # log útil p/ ver 400/401/403 e o erro da Meta no terminal
        print("WA send_text ERROR:", r.status_code, r.text)
        raise e
    return r.json()

def send_template(to_e164: str, template_name: str, lang="pt_BR", components=None) -> dict:
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": components or [],
        },
    }
    r = requests.post(BASE_URL, json=payload, headers=HEADERS, timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        print("WA send_template ERROR:", r.status_code, r.text)
        raise e
    return r.json()

# normalizador (igual ao que já te passei — se ainda não tiver)
import re
def normalizar_e164_br(telefone: str) -> str | None:
    if not telefone:
        return None
    dig = re.sub(r"\D", "", telefone)
    if dig.startswith("0"):
        dig = dig[1:]
    if dig.startswith("55"):
        dig = dig[2:]
    if len(dig) < 10 or len(dig) > 11:
        return None
    return f"+55{dig}"
