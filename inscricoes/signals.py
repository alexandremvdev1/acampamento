# inscricoes/signals.py
from __future__ import annotations

import logging
import re
import secrets
import string

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Paroquia, EventoAcampamento, Ministerio, Grupo, Pagamento

logger = logging.getLogger("django")
User = get_user_model()  # AUTH_USER_MODEL


# =========================
# Helpers genéricos
# =========================
def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    return request.META.get("REMOTE_ADDR")


def gerar_senha_aleatoria(tamanho: int = 10) -> str:
    """Senha aleatória (letras+algarismos) usando 'secrets' (seguro)."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(tamanho))


def gerar_username_unico(nome: str) -> str:
    """
    Base de até 10 chars alfanuméricos minúsculos; acrescenta sufixo numérico se já existir.
    """
    base = re.sub(r"\W+", "", (nome or "").lower())[:10] or "paroquia"
    username = base
    n = 1
    while User.objects.filter(username=username).exists():
        suf = str(n)
        corte = max(1, 10 - len(suf))
        username = f"{base[:corte]}{suf}"
        n += 1
    return username


def _site_base() -> str:
    """
    Retorna o domínio base (com protocolo), sem barra final.
    Aceita SITE_DOMAIN como 'meusite.com' ou 'https://meusite.com'.
    """
    base = (getattr(settings, "SITE_DOMAIN", "") or "").strip()
    if base and not base.startswith(("http://", "https://")):
        base = "https://" + base
    return base.rstrip("/")


def _InscricaoModel():
    """
    Resolve o modelo Inscricao em runtime para evitar NameError e ciclos de import.
    """
    return apps.get_model("inscricoes", "Inscricao")


# =========================
# Logs de login/logout
# =========================
@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    logger.info(f"LOGIN: {user.username} | IP: {get_client_ip(request)}")


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    logger.info(f"LOGOUT: {user.username} | IP: {get_client_ip(request)}")


# =========================
# Criação automática de usuário para Paróquia
# =========================
@receiver(post_save, sender=Paroquia)
def criar_usuario_paroquia(sender, instance: Paroquia, created: bool, **kwargs):
    """
    Ao criar uma Paróquia, gera um usuário admin_paroquia com credenciais
    e envia e-mail (se houver e-mail cadastrado).
    """
    if not created:
        return

    # evita duplicar se já houver admin da mesma paróquia
    if User.objects.filter(paroquia=instance, tipo_usuario="admin_paroquia").exists():
        logger.info(f"Usuário admin_paroquia já existe para {instance.nome}.")
        return

    senha = gerar_senha_aleatoria(10)
    username = gerar_username_unico(instance.nome)

    user = User.objects.create_user(
        username=username,
        email=instance.email or "",
        password=senha,
        tipo_usuario="admin_paroquia",
        paroquia=instance,
    )

    base = _site_base()
    link_alterar = f"{base}/conta/alterar/{user.pk}/" if base else f"/conta/alterar/{user.pk}/"

    if instance.email:
        try:
            send_mail(
                subject="📬 Seus dados de acesso ao sistema de inscrição",
                message=(
                    f"Olá {instance.responsavel or instance.nome},\n\n"
                    f"Sua paróquia {instance.nome} foi cadastrada com sucesso!\n\n"
                    f"🔐 Usuário: {username}\n"
                    f"🔑 Senha: {senha}\n\n"
                    f"Você pode alterar seu nome de usuário e senha neste link:\n"
                    f"🔗 {link_alterar}\n\n"
                    f"🙏 Que Deus abençoe seu trabalho!\n"
                    f"👨‍💻 Equipe do Sistema de Inscrição"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[instance.email],
                fail_silently=False,
            )
            logger.info(f"E-mail de credenciais enviado para {instance.email}.")
        except Exception as e:
            logger.exception(f"Falha ao enviar e-mail para {instance.email}: {e}")
    else:
        logger.warning(
            f"Paróquia '{instance.nome}' criada sem e-mail. "
            f"Usuário '{username}' gerado, mas e-mail não foi enviado."
        )


# =========================
# Catálogo GLOBAL (fixo) de Ministérios e Grupos com cores
# =========================
MINISTERIOS_FIXOS = [
    "Capela/Liturgia",
    "Música",
    "Intercessão",
    "Cozinha",
    "Secretaria/Recepção",
    "Manutenção/Logística",
    "Recreação",
    "Comunicação/Mídias",
    "Farmácia/Primeiros-Socorros",
    "Ambientação",
    "Apoio",
    "Cantina/Livraria",
]

# nome → hex (deve bater com CORES_PADRAO no models.py)
GRUPOS_FIXOS = {
    "Amarelo":  "#F59E0B",
    "Vermelho": "#EF4444",
    "Azul":     "#3B82F6",
    "Verde":    "#10B981",
}


def _eh_servos(tipo: str | None) -> bool:
    return (tipo or "").strip().lower() == "servos"


def _garantir_catalogo_global():
    """
    Garante a existência (global) dos Ministérios e Grupos fixos.
    Não referencia evento.ministerios nem evento.grupos.
    """
    # Ministérios globais
    for nome in MINISTERIOS_FIXOS:
        Ministerio.objects.get_or_create(
            nome=nome,
            defaults={"descricao": f"Ministério de {nome}", "ativo": True},
        )

    # Grupos globais (com coerência de cor)
    for nome, hexcor in GRUPOS_FIXOS.items():
        g, _ = Grupo.objects.get_or_create(
            nome=nome,
            defaults={"cor_nome": nome, "cor_hex": hexcor},
        )
        # Se já existe e a cor diverge, alinhar
        to_update = []
        if g.cor_nome != nome:
            g.cor_nome = nome
            to_update.append("cor_nome")
        if not g.cor_hex or g.cor_hex.upper() != hexcor.upper():
            g.cor_hex = hexcor
            to_update.append("cor_hex")
        if to_update:
            g.save(update_fields=to_update)


@receiver(pre_save, sender=EventoAcampamento)
def _memorizar_tipo_antigo(sender, instance: EventoAcampamento, **kwargs):
    """
    Antes de salvar, guarda tipo antigo no instance para detectar mudança para 'servos'.
    """
    if instance.pk:
        try:
            antigo = sender.objects.only("tipo").get(pk=instance.pk)
            instance._tipo_antigo = antigo.tipo  # atributo transitório
        except sender.DoesNotExist:
            instance._tipo_antigo = None
    else:
        instance._tipo_antigo = None


@receiver(post_save, sender=EventoAcampamento)
def criar_catalogos_globais_para_servos(sender, instance: EventoAcampamento, created: bool, **kwargs):
    """
    NOVO fluxo, compatível com o modelo atual:
    - Se CRIADO como 'servos' → garante catálogo GLOBAL de ministérios e grupos.
    - Se ATUALIZADO e mudou para 'servos' → idem.
    (Não cria objetos atrelados ao evento.)
    """
    def _do():
        _garantir_catalogo_global()
        logger.info("Catálogos globais (ministérios e grupos) garantidos.")

    if created and _eh_servos(instance.tipo):
        transaction.on_commit(_do)
        return

    tipo_antigo = getattr(instance, "_tipo_antigo", None)
    if not created and not _eh_servos(tipo_antigo) and _eh_servos(instance.tipo):
        transaction.on_commit(_do)


# =========================
# Pagamento confirmado → espelhar na inscrição e no par
# =========================
def _get_par(insc):
    """Acha a inscrição pareada (casais). Tenta property e relações comuns."""
    for attr in ("par", "inscricao_pareada", "pareada_por"):
        try:
            par = getattr(insc, attr, None)
            if par and par.evento_id == insc.evento_id:
                return par
        except Exception:
            pass
    return None


@receiver(post_save, sender=Pagamento)
def espelhar_pagamento_no_par(sender, instance: Pagamento, created, **kwargs):
    """
    Se um Pagamento ficar CONFIRMADO, marca pagamento_confirmado=True na inscrição
    e também na inscrição pareada (se houver).
    """
    insc = getattr(instance, "inscricao", None)
    if not insc:
        return

    # Só quando confirmado
    if instance.status != Pagamento.StatusPagamento.CONFIRMADO:
        return

    Inscricao = _InscricaoModel()  # resolve o modelo aqui

    # 1) Garante o flag na própria inscrição
    if not insc.pagamento_confirmado:
        Inscricao.objects.filter(pk=insc.pk, pagamento_confirmado=False).update(
            pagamento_confirmado=True,
            inscricao_concluida=True,   # remova se não usar
        )

    # 2) Marca o PAR também (se existir)
    par = _get_par(insc)
    if par and not par.pagamento_confirmado:
        Inscricao.objects.filter(pk=par.pk, pagamento_confirmado=False).update(
            pagamento_confirmado=True,
            inscricao_concluida=True,   # remova se não usar
        )
