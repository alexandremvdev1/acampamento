# inscricoes/signals.py
from __future__ import annotations

import logging
import re
import secrets
import string

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from .models import Paroquia, EventoAcampamento, Ministerio

logger = logging.getLogger("django")
User = get_user_model()  # usa AUTH_USER_MODEL


# =========================
# Helpers genéricos
# =========================
def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    return request.META.get("REMOTE_ADDR")


def gerar_senha_aleatoria(tamanho: int = 10) -> str:
    """
    Senha aleatória (letras+algarismos) usando 'secrets' (seguro).
    """
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
# Ministérios padrão (evento tipo Servos)
# =========================
MINISTERIOS_PADRAO = [
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


def _eh_servos(tipo: str | None) -> bool:
    return (tipo or "").strip().lower() == "servos"


def _criar_ministerios_padrao(evento: EventoAcampamento) -> None:
    """
    Cria (se necessário) os ministérios padrão para eventos de Servos.
    Usa on_commit para rodar após o evento estar persistido.
    """
    def _do():
        existentes = set(evento.ministerios.values_list("nome", flat=True))
        novos = [Ministerio(evento=evento, nome=n) for n in MINISTERIOS_PADRAO if n not in existentes]
        if novos:
            Ministerio.objects.bulk_create(novos, ignore_conflicts=True)
            logger.info("Ministérios padrão criados para o evento '%s'.", evento.nome)
        else:
            logger.info("Nenhum ministério novo necessário para o evento '%s'.", evento.nome)

    transaction.on_commit(_do)


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
def criar_ministerios_padrao_servos(sender, instance: EventoAcampamento, created: bool, **kwargs):
    """
    - Se CRIADO como 'servos' → cria ministérios padrão.
    - Se ATUALIZADO e mudou para 'servos' → cria ministérios padrão.
    """
    if created and _eh_servos(instance.tipo):
        _criar_ministerios_padrao(instance)
        return

    tipo_antigo = getattr(instance, "_tipo_antigo", None)
    if not created and not _eh_servos(tipo_antigo) and _eh_servos(instance.tipo):
        _criar_ministerios_padrao(instance)
