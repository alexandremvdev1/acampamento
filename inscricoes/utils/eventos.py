# inscricoes/utils/eventos.py
def tipo_efetivo_evento(evento) -> str:
    """
    Retorna o tipo 'efetivo' do formulário:
    - 'casais' quando for um evento de servos vinculado a um principal de casais
    - caso contrário, o tipo original do evento
    """
    tipo = (getattr(evento, "tipo", "") or "").lower()
    if tipo == "servos":
        principal = getattr(evento, "evento_relacionado", None)
        if principal and (getattr(principal, "tipo", "") or "").lower() == "casais":
            return "casais"
    return tipo
