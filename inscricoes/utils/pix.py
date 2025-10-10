# inscricoes/services/utils/pix.py
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
import re
import unicodedata
import random
import string

# --------------------------
# Helpers padrão BR Code Pix
# --------------------------

def _num2(n: int) -> str:
    # 2 dígitos, zero-padded (comprimento dos campos)
    return f"{n:02d}"

def _clean_ascii(s: str, maxlen: int | None = None, upper: bool = True) -> str:
    s = s or ""
    # remove acentos e qualquer char fora de ASCII visível
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Za-z0-9 \-\.]", "", s).strip()
    if upper:
        s = s.upper()
    if maxlen:
        s = s[:maxlen]
    return s

def _crc16_ccitt(data: bytes, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    """
    CRC16-CCITT (XModem). Especificação do BR Code usa polinômio 0x1021 e init 0xFFFF.
    """
    crc = init
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if (crc & 0x8000) != 0:
                crc = ((crc << 1) & 0xFFFF) ^ poly
            else:
                crc = (crc << 1) & 0xFFFF
    return crc & 0xFFFF

def _tlv(id_: str, value: str) -> str:
    return f"{id_}{_num2(len(value))}{value}"

def _txid_default() -> str:
    base = "REPASSE"
    sufixo = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return (base + "-" + sufixo)[:25]

# --------------------------
# EMV Pix (estático)
# --------------------------

def build_pix_emv(
    *,
    chave_pix: str,
    valor: Decimal | float | str | int,
    descricao: str | None = None,
    nome_recebedor: str,
    cidade_recebedor: str,
    txid: str | None = None,
    incluir_valor: bool = True,
    ponto_iniciacao: str = "12",  # "12" (estático) / "11" (dinâmico)
) -> str:
    """
    Monta payload EMV conforme BR Code Pix (BCB/Febraban).
    Campos principais:
      - 00: Payload Format Indicator -> "01"
      - 01: Point of Initiation Method -> "11" (dinâmico) ou "12" (estático)
      - 26: Merchant Account Information (GUI + chave + descrição)
      - 52: Merchant Category Code -> "0000"
      - 53: Currency -> "986"
      - 54: Amount -> "123.45" (opcional em estático, mas aceitável)
      - 58: Country Code -> "BR"
      - 59: Merchant Name (máx 25)
      - 60: Merchant City (máx 15)
      - 62: Additional Data Field (TXID máx 25)
      - 63: CRC (calculado sobre tudo + "6304")
    """

    # Sanitização e limites
    nome = _clean_ascii(nome_recebedor, maxlen=25, upper=True)
    cidade = _clean_ascii(cidade_recebedor, maxlen=15, upper=True)
    chave = (chave_pix or "").strip()
    if not chave:
        raise ValueError("Chave Pix vazia.")

    # Valor
    if isinstance(valor, Decimal):
        v = valor
    else:
        v = Decimal(str(valor))
    v = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # TXID
    if not txid:
        txid = _txid_default()
    txid = _clean_ascii(txid, maxlen=25, upper=True)
    if not txid:
        txid = "REPASSE"

    # 26: Merchant Account Information (GUI + chave + desc opcional)
    gui = _tlv("00", "br.gov.bcb.pix")
    kv = _tlv("01", chave)
    mai_inner = [gui, kv]
    desc = (descricao or "").strip()
    if desc:
        # Campo 02 (description) é opcional; limite prático ~ 72 chars
        desc_clean = _clean_ascii(desc, maxlen=72, upper=False)
        if desc_clean:
            mai_inner.append(_tlv("02", desc_clean))
    mai = _tlv("26", "".join(mai_inner))

    # Campos fixos
    pfi = _tlv("00", "01")
    pim = _tlv("01", ponto_iniciacao)       # "12" estático
    mcc = _tlv("52", "0000")
    cur = _tlv("53", "986")
    cty = _tlv("58", "BR")
    mname = _tlv("59", nome)
    mcity = _tlv("60", cidade)

    # 54 (valor) — permitido em estático e amplamente aceito; se quiser ocultar, set incluir_valor=False
    amount = _tlv("54", f"{v:.2f}") if incluir_valor and v > 0 else ""

    # 62: Additional Data Field (TXID)
    addl = _tlv("62", _tlv("05", txid))

    # Montagem SEM o CRC
    partial = "".join([pfi, pim, mai, mcc, cur, amount, cty, mname, mcity, addl])

    # 63: CRC (calcula sobre partial + "6304")
    to_crc = (partial + "6304").encode("ascii")
    crc = _crc16_ccitt(to_crc)
    crc_hex = f"{crc:04X}"
    full = partial + _tlv("63", crc_hex)
    return full
