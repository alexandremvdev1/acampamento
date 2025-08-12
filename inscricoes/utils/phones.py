# inscricoes/utils/phones.py
import re
from typing import Optional

E164_BR_REGEX = re.compile(r'^\+55\d{10,11}$')

def normalizar_e164_br(raw: str) -> Optional[str]:
    """
    Converte telefones BR variados p/ E.164: +55 + (10|11) dígitos.
    Aceita coisas como: '063 92001-3103', '(63) 2001-3103', '+55 63 92001-3103', '063920013103', etc.
    Retorna None se não conseguir normalizar.
    """
    if not raw:
        return None

    # pega só dígitos
    dig = re.sub(r'\D', '', raw)

    # remove zero inicial do DDD (algumas pessoas digitam 0DDD)
    if dig.startswith('0'):
        dig = dig[1:]

    # remove DDI 55 se já vier com ele
    if dig.startswith('55'):
        dig = dig[2:]

    # agora deve restar 10 (fixo) ou 11 (celular) dígitos
    if len(dig) not in (10, 11):
        return None

    return f'+55{dig}'

def validar_e164_br(e164: str) -> bool:
    return bool(E164_BR_REGEX.match(e164 or ''))
