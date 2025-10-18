# inscricoes/mercadopago_utils.py

import mercadopago
import logging

def _mp_client_by_paroquia(paroquia):
    """
    Retorna uma instância do SDK do Mercado Pago.
    Se paroquia for None, retorna uma config genérica.
    """
    access_token = "SEU_ACCESS_TOKEN_AQUI"  # colocar um token válido ou pegar do banco
    return mercadopago.SDK(access_token.strip())

def _sincronizar_pagamento(mp, inscricao, payment_id):
    """
    Função de sincronização de pagamento. Pode apenas logar no começo.
    """
    logging.info("Sincronizando pagamento %s para inscrição %s", payment_id, inscricao.id)
    # aqui você chamaria mp.payment().get(payment_id) e atualizaria o status
    return True
