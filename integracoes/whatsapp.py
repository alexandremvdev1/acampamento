# integracoes/whatsapp.py
from __future__ import annotations

import re
import requests
from typing import Any, Dict, List, Optional

from django.conf import settings


# ------------------------------------------------------------------------------
# Helpers dinâmicos (não “congelam” token/IDs no import)
# ------------------------------------------------------------------------------
def _base_url() -> str:
    """Monta a URL base da API de mensagens com a versão/phone_id atuais do settings."""
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v20.0")
    phone_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
    if not phone_id:
        raise RuntimeError(
            "Config WhatsApp ausente: defina WHATSAPP_PHONE_NUMBER_ID no settings."
        )
    return f"https://graph.facebook.com/{api_version}/{phone_id}/messages"


def _headers() -> Dict[str, str]:
    """Cabeçalhos com o token atual do settings."""
    token = getattr(settings, "WHATSAPP_TOKEN", None)
    if not token:
        raise RuntimeError(
            "Config WhatsApp ausente: defina WHATSAPP_TOKEN no settings."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _post_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST na API da Meta; imprime o corpo do erro em caso de falha para facilitar debug."""
    r = requests.post(_base_url(), json=payload, headers=_headers(), timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # diagnóstico rápido (401/403/400 etc. — incluindo mensagem da Meta)
        print("WA ERROR:", r.status_code, r.text)
        raise e
    return r.json()


# ------------------------------------------------------------------------------
# Normalizador de telefone 🇧🇷 -> E.164
# ------------------------------------------------------------------------------
def normalizar_e164_br(telefone: str) -> Optional[str]:
    """
    Converte um telefone BR para E.164: +55DDDNÚMERO
    Aceita: (63) 92001-3103, 063920013103, +5563920013103 etc.
    Retorna None se inválido.
    """
    if not telefone:
        return None
    dig = re.sub(r"\D", "", telefone or "")
    if dig.startswith("0"):
        dig = dig[1:]
    if dig.startswith("55"):
        dig = dig[2:]
    # 10 (fixo 8 dígitos) ou 11 (celular 9 dígitos)
    if len(dig) < 10 or len(dig) > 11:
        return None
    return f"+55{dig}"


# ------------------------------------------------------------------------------
# Envio de TEXTO livre (válido dentro da janela de 24h)
# ------------------------------------------------------------------------------
def send_text(to_e164: str, body: str) -> Dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"body": body},
    }
    return _post_meta(payload)


# ------------------------------------------------------------------------------
# Envio de TEMPLATE (HSM)
# ------------------------------------------------------------------------------
def _build_body_component(params: List[str]) -> Dict[str, Any]:
    """Componente BODY com parâmetros textuais (substituem {{1}}, {{2}}, ...)."""
    return {
        "type": "body",
        "parameters": [{"type": "text", "text": str(x)} for x in params],
    }


def _build_button_url_component(url_dynamic_param: str, index: int = 0) -> Dict[str, Any]:
    """
    Botão de URL DINÂMICO (para templates com {{1}} na URL do botão).
    index = posição do botão no template (0, 1, 2...).
    """
    return {
        "type": "button",
        "sub_type": "url",
        "index": str(index),
        "parameters": [{"type": "text", "text": url_dynamic_param}],
    }


def send_template(
    to_e164: str,
    template_name: str,
    lang: str = "pt_BR",
    components: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
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
    return _post_meta(payload)


# ------------------------------------------------------------------------------
# Catálogo dos templates aprovados (nomes/idiomas/esperado)
#    → Ajustado aos que você listou via API:
#       - inscricao_recebida_v2                (APPROVED) BODY: 3
#       - selecao_pagamento_util_v2            (APPROVED) BODY: 3
#       - pagamento_confirmado_util_v2         (APPROVED) BODY: 2
# ------------------------------------------------------------------------------
WA_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "INSCRICAO_RECEBIDA": {
        "name": "inscricao_recebida_v2",
        "lang": "pt_BR",
        "expected_body_params": 3,
        "has_dynamic_button": False,  # ajuste se seu template tiver botão dinâmico
    },
    "SELECIONADO_INFO": {
        "name": "selecao_pagamento_util_v2",
        "lang": "pt_BR",
        "expected_body_params": 3,    # nome, evento, URL (no CORPO)
        "has_dynamic_button": True,   # se o botão tiver {{1}}, podemos preencher via url_param
    },
    "PAGAMENTO_RECEBIDO": {
        "name": "pagamento_confirmado_util_v2",
        "lang": "pt_BR",
        "expected_body_params": 2,
        "has_dynamic_button": False,
    },
    "HELLO_WORLD": {
        "name": "hello_world",
        "lang": "en_US",
        "expected_body_params": 0,
        "has_dynamic_button": False,
    },
}


# ------------------------------------------------------------------------------
# Facade por CHAVE (conveniência)
# ------------------------------------------------------------------------------
def send_named_template(
    chave: str,
    telefone_br: str,
    body_params: List[str],
    button_url_param: Optional[str] = None,
    button_index: int = 0,
) -> Dict[str, Any]:
    """
    Envia template usando a chave de WA_TEMPLATES.
    - body_params: valores para {{1}}, {{2}}, ...
    - button_url_param: sufixo que preenche {{1}} da URL do botão (se for DINÂMICO).
    """
    cfg = WA_TEMPLATES[chave]
    tel = normalizar_e164_br(telefone_br)
    if not tel:
        raise ValueError(f"Telefone inválido para BR: {telefone_br!r}")

    # Validação de quantidade de variáveis do BODY
    expected = int(cfg.get("expected_body_params", len(body_params)))
    if len(body_params) != expected:
        raise ValueError(
            f"Template '{cfg['name']}' espera {expected} parâmetros no BODY, "
            f"mas recebeu {len(body_params)}: {body_params!r}"
        )

    components: List[Dict[str, Any]] = [_build_body_component(body_params)]

    # Botão de URL dinâmico (opcional)
    if button_url_param and cfg.get("has_dynamic_button"):
        components.append(_build_button_url_component(button_url_param, index=button_index))

    return send_template(tel, cfg["name"], lang=cfg["lang"], components=components)


# ------------------------------------------------------------------------------
# Helpers de URL
# ------------------------------------------------------------------------------
def _abs_url(path_or_url: Optional[str]) -> str:
    """
    Monta URL absoluta a partir de um caminho (ex.: 'minhas-inscricoes/').
    Se já vier http(s) retorna como está.
    """
    base = getattr(settings, "SITE_DOMAIN", "https://eismeaqui.app.br")
    if not path_or_url:
        path_or_url = "minhas-inscricoes/"
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return f"{base.rstrip('/')}/{path_or_url.lstrip('/')}"


# ------------------------------------------------------------------------------
# Wrappers específicos (pontos de disparo claros)
# ------------------------------------------------------------------------------
def enviar_inscricao_recebida(
    telefone_br: str,
    nome: str,
    evento: str,
    data_hora: str,
) -> Dict[str, Any]:
    """BODY: 1) Nome  2) Evento  3) Data/hora"""
    return send_named_template(
        "INSCRICAO_RECEBIDA",
        telefone_br,
        [nome, evento, data_hora],
    )


def enviar_selecionado_info(
    telefone_br: str,
    nome: str,
    evento: str,
    url_text: Optional[str] = None,
    url_param: Optional[str] = None,
) -> Dict[str, Any]:
    """
    BODY: 1) Nome  2) Evento  3) URL (no corpo do template)
    - url_text: o texto/rota que vai no BODY (3ª variável). Ex.: "minhas-inscricoes" ou URL completa.
    - url_param: se o botão do template tiver URL DINÂMICA com {{1}}, passamos este sufixo para o botão.
    """
    full_url_for_body = _abs_url(url_text or "minhas-inscricoes/")
    return send_named_template(
        "SELECIONADO_INFO",
        telefone_br,
        [nome, evento, full_url_for_body],  # ← 3 variáveis (conforme template aprovado)
        button_url_param=url_param,         # opcional, só se o botão tiver {{1}}
        button_index=0,
    )


def enviar_pagamento_recebido(
    telefone_br: str,
    nome: str,
    evento: str,
) -> Dict[str, Any]:
    """BODY: 1) Nome  2) Evento"""
    return send_named_template(
        "PAGAMENTO_RECEBIDO",
        telefone_br,
        [nome, evento],
    )


# ------------------------------------------------------------------------------
# (Opcional) utilitário para listar templates da WABA — útil para debug no shell
# ------------------------------------------------------------------------------
def listar_templates_waba() -> Dict[str, Any]:
    """
    Lista os templates aprovados da sua WABA (útil para conferir nomes/idiomas).
    Uso no shell:
        from integracoes.whatsapp import listar_templates_waba
        data = listar_templates_waba()
        for t in data.get("data", []):
            print(t.get("name"), t.get("status"))
    """
    waba_id = getattr(settings, "WHATSAPP_WABA_ID", None)
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v20.0")
    token = getattr(settings, "WHATSAPP_TOKEN", None)
    if not waba_id or not token:
        raise RuntimeError("Defina WHATSAPP_WABA_ID e WHATSAPP_TOKEN no settings.")
    url = f"https://graph.facebook.com/{api_version}/{waba_id}/message_templates"
    r = requests.get(url, params={"access_token": token}, timeout=30)
    r.raise_for_status()
    return r.json()
