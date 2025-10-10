# inscricoes/services/mercadopago_owner.py

import io, base64
try:
    import qrcode
except ImportError:
    qrcode = None

from decimal import Decimal
from ..utils.pix import build_pix_emv  # sua função que monta o EMV Pix

class MercadoPagoOwnerService:
    def __init__(
        self, *,
        access_token: str,
        notif_url: str | None = None,
        chave_pix: str,
        nome_recebedor: str,
        cidade_recebedor: str,
        public_key: str | None = None,
    ):
        self.access_token = access_token
        self.public_key = public_key
        self.notif_url = notif_url
        # >>> TUDO do banco:
        self.chave_pix = (chave_pix or "").strip()
        self.nome_recebedor = (nome_recebedor or "RECEBEDOR")[:25]
        self.cidade_recebedor = (cidade_recebedor or "SAO PAULO")[:15]

    def create_pix_charge(self, descricao: str, valor_decimal: Decimal):
        if not self.chave_pix:
            raise ValueError("Chave Pix do dono não configurada.")

        emv = build_pix_emv(
            chave_pix=self.chave_pix,
            valor=valor_decimal,
            descricao=descricao,
            nome_recebedor=self.nome_recebedor,
            cidade_recebedor=self.cidade_recebedor,
            txid="REPASSE"
        )

        png_b64 = None
        if qrcode:
            buf = io.BytesIO()
            qrcode.make(emv).save(buf, format="PNG")
            png_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        class Resp: pass
        r = Resp()
        r.id = "mock-pix-id-123"      # quando integrar de fato, retorne o id real da API
        r.qr_code_text = emv          # EMV válido
        r.qr_code_base64 = png_b64    # opcional
        return r
