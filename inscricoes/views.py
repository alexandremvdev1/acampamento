# -*- coding: utf-8 -*-
# Ã‚â€”Ã‚â€”Ã‚â€” Python stdlib
import os
import csv
import json
import logging
import io
import base64
from django.db.models import QuerySet
from typing import Optional, Iterable, Any, Dict
from collections import OrderedDict
from uuid import UUID
from uuid import uuid4, UUID
from django.core.files.storage import default_storage
from io import BytesIO
from types import SimpleNamespace
from decimal import Decimal
from urllib.parse import urljoin
from datetime import timedelta, timezone as dt_tz
from django.contrib.auth.views import LoginView
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseForbidden
from django.views.decorators.cache import never_cache
from typing import Optional
from django.core.exceptions import FieldError
from .forms import FormBasicoPagamentoPublico
from .models import Inscricao, InscricaoStatus
from django.conf import settings
from .services.mercadopago_owner import MercadoPagoOwnerService
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Q, Sum, Count
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.core.exceptions import ValidationError
from .models import Inscricao, EventoAcampamento, InscricaoStatus
from django.db.models import Prefetch, Count, Q
from decimal import Decimal
from django.core.files.base import ContentFile
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum
import re
from datetime import date, datetime
import uuid
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date, parse_datetime

from .models import EventoAcampamento, Participante, Inscricao, InscricaoCasais
from .forms import ParticipanteInicialForm, InscricaoCasaisForm
# Ã‚â€”Ã‚â€”Ã‚â€” Terceiros
import mercadopago
import qrcode
from django.forms import modelform_factory

# Ã‚â€”Ã‚â€”Ã‚â€” App (helpers, models, forms)
from .helpers_mp_owner import mp_owner_client

from .models import (
    MercadoPagoConfig,
    PastoralMovimento,
    VideoEventoAcampamento,
    CrachaTemplate,
    Paroquia,
    EventoAcampamento,
    Inscricao,
    InscricaoSenior,
    InscricaoJuvenil,
    InscricaoMirim,
    InscricaoServos,
    Conjuge,
    Pagamento,
    Participante,
    PoliticaPrivacidade,
    Contato,
    PreferenciasComunicacao,
    PoliticaReembolso,
    InscricaoCasais,
    InscricaoEvento,
    InscricaoRetiro,
    Repasse,
    MercadoPagoOwnerConfig,
    BaseInscricao,
    Ministerio,
    Grupo,
    AlocacaoGrupo,
    AlocacaoMinisterio
)

from .forms import (
    ContatoForm,
    DadosSaudeForm,
    PastoralMovimentoForm,
    VideoEventoForm,
    AlterarCredenciaisForm,
    PoliticaPrivacidadeForm,
    ParoquiaForm,
    UserAdminParoquiaForm,
    ParticipanteInicialForm,
    ParticipanteEnderecoForm,
    InscricaoSeniorForm,
    InscricaoJuvenilForm,
    InscricaoMirimForm,
    InscricaoServosForm,
    EventoForm,
    ConjugeForm,
    MercadoPagoConfigForm,
    PagamentoForm,
    UserCreationForm,
    PoliticaReembolsoForm,
    AdminParoquiaCreateForm,
    InscricaoCasaisForm,
    InscricaoEventoForm,
    InscricaoRetiroForm,
    AlocarInscricaoForm,
)



User = get_user_model()

# --- PROGRESSO DA INSCRIÃƒâ€¡ÃƒÆ’O (ordem: endereÃƒÂ§o -> personalizado -> contato -> saÃƒÂºde) ---



def _tem_endereco_completo(p: Participante) -> bool:
    return all([
        bool(getattr(p, "CEP", "")),
        bool(getattr(p, "endereco", "")),
        bool(getattr(p, "numero", "")),
        bool(getattr(p, "bairro", "")),
        bool(getattr(p, "cidade", "")),
        bool(getattr(p, "estado", "")),
    ])

def _tem_personalizado(insc: Inscricao) -> bool:
    rel_por_tipo = {
        "senior":  "inscricaosenior",
        "juvenil": "inscricaojuvenil",
        "mirim":   "inscricaomirim",
        "servos":  "inscricaoservos",
        "casais":  "inscricaocasais",
        "evento":  "inscricaoevento",
        "retiro":  "inscricaoretiro",
    }
    tipo_eff = _tipo_formulario_evento(insc.evento)
    rel = rel_por_tipo.get(tipo_eff)
    return bool(rel and getattr(insc, rel, None))


def _tem_contato(insc: Inscricao) -> bool:
    return bool(
        getattr(insc, "contato_emergencia_nome", "") and
        getattr(insc, "contato_emergencia_telefone", "")
    )

def _proxima_etapa_forms(insc: Inscricao) -> dict | None:
    p = insc.participante
    ev = insc.evento

    # 0) EndereÃƒÂ§o (fica dentro de 'inscricao_inicial', retomamos via querystring)
    if not _tem_endereco_completo(p):
        retomar_url = reverse("inscricoes:inscricao_inicial", args=[ev.slug])
        retomar_url += f"?retomar=1&pid={p.id}"
        return {"step": "endereco", "next_url": retomar_url}

    # 1) Form personalizado (por tipo de evento)
    if not _tem_personalizado(insc):
        return {"step": "personalizado", "next_url": reverse("inscricoes:formulario_personalizado", args=[insc.id])}

    # 2) Contato
    if not _tem_contato(insc):
        return {"step": "contato", "next_url": reverse("inscricoes:formulario_contato", args=[insc.id])}

    # 3) SaÃƒÂºde (marca envio ao salvar)
    if not insc.inscricao_enviada:
        return {"step": "saude", "next_url": reverse("inscricoes:formulario_saude", args=[insc.id])}

    # 4) Depois do envio: se selecionado e nÃƒÂ£o pago ? pagamento; senÃƒÂ£o ? status
    if insc.foi_selecionado and not insc.pagamento_confirmado:
        return {"step": "pagamento", "next_url": reverse("inscricoes:aguardando_pagamento", args=[insc.id])}

    return {"step": "status", "next_url": reverse("inscricoes:ver_inscricao", args=[insc.id])}


@login_required
def home_redirect(request):
    user = request.user
    if hasattr(user, 'is_admin_geral') and user.is_admin_geral():
        return redirect('inscricoes:admin_geral_dashboard')
    elif hasattr(user, 'is_admin_paroquia') and user.is_admin_paroquia():
        return redirect('inscricoes:admin_paroquia_painel')
    else:
        return redirect('inscricoes:login')

@login_required
def admin_geral_home(request):
    return HttpResponse("Bem-vindo, Administrador Geral!")

@login_required
def admin_paroquia_home(request):
    # Supondo que o usuÃƒÂ¡rio tenha atributo 'paroquia' diretamente ou via perfil
    paroquia = getattr(request.user, 'paroquia', None)
    nome_paroquia = paroquia.nome if paroquia else 'Sem ParÃƒÂ³quia'
    return HttpResponse(f"Bem-vindo, Admin da Paroquia: {nome_paroquia}")

def is_admin_geral(user):
    return user.is_authenticated and user.is_admin_geral()

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_dashboard(request):
    total_paroquias = Paroquia.objects.count()
    total_eventos = EventoAcampamento.objects.count()
    total_inscricoes = Inscricao.objects.count()
    total_inscricoes_confirmadas = Inscricao.objects.filter(pagamento_confirmado=True).count()
    total_usuarios = User.objects.filter(tipo_usuario='admin_paroquia').count()

    ultimas_paroquias = Paroquia.objects.order_by('-id')[:5]
    proximos_eventos = (
    EventoAcampamento.objects.filter(data_inicio__gte=dj_tz.localdate()).order_by('data_inicio')[:5])
    inscricoes_recentes = Inscricao.objects.order_by('-data_inscricao')[:5]

    context = {
        'total_paroquias': total_paroquias,
        'total_eventos': total_eventos,
        'total_inscricoes': total_inscricoes,
        'total_inscricoes_confirmadas': total_inscricoes_confirmadas,
        'total_usuarios': total_usuarios,
        'ultimas_paroquias': ultimas_paroquias,
        'proximos_eventos': proximos_eventos,
        'inscricoes_recentes': inscricoes_recentes,
    }
    return render(request, 'inscricoes/admin_geral_dashboard.html', context)


def is_admin_geral(user):
    return user.is_authenticated and user.is_admin_geral()

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_list_paroquias(request):
    paroquias = Paroquia.objects.all()
    return render(request, 'inscricoes/admin_geral_list_paroquias.html', {'paroquias': paroquias})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_create_paroquia(request):
    if request.method == 'POST':
        form = ParoquiaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_list_paroquias')
    else:
        form = ParoquiaForm()
    return render(request, 'inscricoes/admin_geral_form_paroquia.html', {'form': form})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_edit_paroquia(request, pk):
    paroquia = get_object_or_404(Paroquia, pk=pk)
    if request.method == 'POST':
        form = ParoquiaForm(request.POST, instance=paroquia)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_list_paroquias')
    else:
        form = ParoquiaForm(instance=paroquia)
    return render(request, 'inscricoes/admin_geral_form_paroquia.html', {'form': form})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_delete_paroquia(request, pk):
    paroquia = get_object_or_404(Paroquia, pk=pk)
    if request.method == 'POST':
        paroquia.delete()
        return redirect('inscricoes:admin_geral_list_paroquias')
    return render(request, 'inscricoes/admin_geral_confirm_delete.html', {'obj': paroquia, 'tipo': 'ParÃƒÂ³quia'})

def _is_admin_geral(user):
    return (
        user.is_authenticated and (
            getattr(user, "is_superuser", False) or
            getattr(user, "is_staff", False) or
            user.groups.filter(name__in=["AdminGeral","AdministradorGeral"]).exists() or
            getattr(user, "tipo_usuario", "") == "admin_geral"
        )
    )

@login_required
@user_passes_test(_is_admin_geral)
@require_POST
def admin_geral_set_status_paroquia(request, pk):
    paroquia = get_object_or_404(Paroquia, pk=pk)
    status = (request.POST.get("status") or "").lower()
    if status not in ("ativa","inativa"):
        return HttpResponse("Status invÃƒÂ¡lido.", status=400)
    paroquia.status = status
    paroquia.save(update_fields=["status"])
    messages.success(request, f"ParÃƒÂ³quia marcada como {status}.")
    return redirect(request.POST.get("next") or reverse("inscricoes:admin_geral_list_paroquias"))
# -------- UsuÃƒÂ¡rios Admin ParÃƒÂ³quia --------
def _is_ajax(req):
    return (
        req.headers.get('x-requested-with') == 'XMLHttpRequest'
        or req.headers.get('HX-Request') == 'true'
        or 'application/json' in (req.headers.get('Accept',''))
    )

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_admin_geral())
@require_POST
def admin_geral_toggle_status_paroquia(request, paroquia_id: int):
    paroquia = get_object_or_404(Paroquia, id=paroquia_id)

    # se vier explicitamente active=true/false, usa; senÃƒÂ£o alterna
    if "active" in request.POST:
        ativa = (request.POST.get("active") or "").strip().lower() in {"1","true","on","yes","sim"}
    else:
        ativa = (paroquia.status != "ativa")

    paroquia.status = "ativa" if ativa else "inativa"
    paroquia.save(update_fields=["status"])

    msg = "ParÃƒÂ³quia ativada" if ativa else "ParÃƒÂ³quia desativada"

    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "id": paroquia.id,
            "ativa": ativa,
            "status": paroquia.status,
            "msg": msg,
        })

    messages.success(request, msg)
    return redirect(request.POST.get("next") or "inscricoes:admin_geral_list_paroquias")



@login_required
@user_passes_test(is_admin_geral)
@require_POST
def admin_geral_set_status_paroquia(request, pk: int):
    paroquia = get_object_or_404(Paroquia, pk=pk)
    novo = (request.POST.get("status") or "").strip().lower()
    if novo not in ("ativa", "inativa"):
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "status invÃƒÂ¡lido"}, status=400)
        messages.error(request, "Status invÃƒÂ¡lido.")
        return redirect(request.META.get('HTTP_REFERER', reverse('inscricoes:admin_geral_list_paroquias')))

    paroquia.status = novo
    paroquia.save(update_fields=["status"])

    if _is_ajax(request):
        return JsonResponse({"ok": True, "status": paroquia.status})

    messages.success(request, f"Status atualizado para {paroquia.status}.")
    return redirect(request.META.get('HTTP_REFERER', reverse('inscricoes:admin_geral_list_paroquias')))

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_list_usuarios(request):
    usuarios = User.objects.filter(tipo_usuario='admin_paroquia')
    return render(request, 'inscricoes/admin_geral_list_usuarios.html', {'usuarios': usuarios})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_create_usuario(request):
    if request.method == 'POST':
        form = UserAdminParoquiaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_list_usuarios')
    else:
        form = UserAdminParoquiaForm()
    return render(request, 'inscricoes/admin_geral_form_usuario.html', {'form': form})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_edit_usuario(request, pk):
    usuario = get_object_or_404(User, pk=pk, tipo_usuario='admin_paroquia')
    if request.method == 'POST':
        form = UserAdminParoquiaForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_list_usuarios')
    else:
        form = UserAdminParoquiaForm(instance=usuario)
    return render(request, 'inscricoes/admin_geral_form_usuario.html', {'form': form})

@login_required
@user_passes_test(is_admin_geral)
def admin_geral_delete_usuario(request, pk):
    usuario = get_object_or_404(User, pk=pk, tipo_usuario='admin_paroquia')
    if request.method == 'POST':
        usuario.delete()
        return redirect('inscricoes:admin_geral_list_usuarios')
    return render(request, 'inscricoes/admin_geral_confirm_delete.html', {'obj': usuario, 'tipo': 'UsuÃƒÂ¡rio'})

def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


@login_required  # se preferir: @login_required(login_url="inscricoes:login")
def admin_paroquia_painel(request, paroquia_id: Optional[int] = None):
    """
    Painel da parÃƒÂ³quia:
    - Admin da parÃƒÂ³quia: sempre usa a parÃƒÂ³quia vinculada ao usuÃƒÂ¡rio.
    - Admin geral: precisa informar paroquia_id (ex.: /painel/3/).
    - Outros: sem acesso.
    """
    user = request.user

    # --- Detecta papÃƒÂ©is com fallback ---
    if hasattr(user, "is_admin_paroquia") and callable(user.is_admin_paroquia):
        is_admin_paroquia = bool(user.is_admin_paroquia())
    else:
        is_admin_paroquia = getattr(user, "tipo_usuario", "") == "admin_paroquia"

    if hasattr(user, "is_admin_geral") and callable(user.is_admin_geral):
        is_admin_geral = bool(user.is_admin_geral())
    else:
        is_admin_geral = bool(getattr(user, "is_superuser", False)) or (
            getattr(user, "tipo_usuario", "") == "admin_geral"
        )

    # --- SeleÃƒÂ§ÃƒÂ£o da parÃƒÂ³quia conforme papel ---
    if is_admin_paroquia:
        paroquia = getattr(user, "paroquia", None)
        if not paroquia:
            messages.error(request, "?? Sua conta nÃƒÂ£o estÃƒÂ¡ vinculada a uma parÃƒÂ³quia.")
            return redirect("inscricoes:logout")

        # se tentarem acessar outra parÃƒÂ³quia via URL, redireciona para a correta
        if paroquia_id and int(paroquia_id) != getattr(user, "paroquia_id", None):
            return redirect(reverse("inscricoes:admin_paroquia_painel"))

    elif is_admin_geral:
        if not paroquia_id:
            messages.error(request, "?? ParÃƒÂ³quia nÃƒÂ£o especificada.")
            return redirect("inscricoes:admin_geral_list_paroquias")
        paroquia = get_object_or_404(Paroquia, id=paroquia_id)

    else:
        messages.error(request, "?? VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para acessar este painel.")
        return redirect("inscricoes:logout")

    # =========================
    #   LISTA DE EVENTOS
    # =========================
    qs_evt = EventoAcampamento.objects.filter(paroquia=paroquia)
    eventos = None
    for ordering in [
        ("-data_inicio", "-created_at"),
        ("-data_inicio",),
        ("-created_at",),
        ("-pk",),
    ]:
        try:
            eventos = qs_evt.order_by(*ordering)
            break
        except FieldError:
            continue
    if eventos is None:
        eventos = qs_evt

    # =========================
    #   FILTROS AUXILIARES
    # =========================
    now = timezone.now()
    today = date.today()

    # Eventos abertos (detecÃƒÂ§ÃƒÂ£o por mÃƒÂºltiplos caminhos):
    # 1) status == 'aberto'
    # 2) inscricoes_abertas == True
    # 3) data_fim >= hoje (fallback)
    aberto_q = Q()
    if _model_has_field(EventoAcampamento, "status"):
        aberto_q |= Q(status__iexact="aberto")
    if _model_has_field(EventoAcampamento, "inscricoes_abertas"):
        aberto_q |= Q(inscricoes_abertas=True)
    if _model_has_field(EventoAcampamento, "data_fim"):
        aberto_q |= Q(data_fim__gte=today)

    eventos_abertos_qs = qs_evt.filter(aberto_q) if aberto_q else qs_evt.none()
    eventos_abertos = eventos_abertos_qs.count()

    # =========================
    #   KPIs (reais)
    # =========================
    insc_qs = Inscricao.objects.filter(evento__paroquia=paroquia)

    total_inscricoes = insc_qs.count()

    # Confirmadas: priorizamos campo booleano pagamento_confirmado
    if _model_has_field(Inscricao, "pagamento_confirmado"):
        total_inscricoes_confirmadas = insc_qs.filter(pagamento_confirmado=True).count()
    else:
        # fallback: se houver campo status, considere 'confirmada'
        if _model_has_field(Inscricao, "status"):
            total_inscricoes_confirmadas = insc_qs.filter(status__iexact="confirmada").count()
        else:
            total_inscricoes_confirmadas = 0  # sem referÃƒÂªncia

    # Pendentes = total - confirmadas (ignorando canceladas aqui)
    pendencias_contagem = max(total_inscricoes - total_inscricoes_confirmadas, 0)

    # =========================
    #   GRÃƒÂFICO: INSCRIÃƒâ€¡Ãƒâ€¢ES POR DIA (30 dias)
    # =========================
    start_30 = now - timedelta(days=29)  # inclui hoje (janela de 30 dias)
    if _model_has_field(Inscricao, "data_inscricao"):
        by_day = (
            insc_qs.filter(data_inscricao__date__gte=start_30.date())
            .annotate(dia=TruncDate("data_inscricao"))
            .values("dia")
            .annotate(qtd=Count("id"))
            .order_by("dia")
        )
    else:
        by_day = []

    # Gera e garante todos os dias (inclusive os sem inscriÃƒÂ§ÃƒÂµes) para linhas contÃƒÂ­nuas
    labels_dias = []
    values_dias = []
    dia_map = {row["dia"]: row["qtd"] for row in by_day} if by_day else {}
    for i in range(30):
        d = (start_30 + timedelta(days=i)).date()
        labels_dias.append(d.strftime("%d/%m"))
        values_dias.append(int(dia_map.get(d, 0)))

    # =========================
    #   GRÃƒÂFICO: INSCRIÃƒâ€¡Ãƒâ€¢ES POR EVENTO (apenas eventos "abertos", top 5)
    # =========================
    if eventos_abertos_qs.exists():
        por_evento = (
            insc_qs.filter(evento__in=eventos_abertos_qs)
            .values(nome=F("evento__nome"))
            .annotate(qtd=Count("id"))
            .order_by("-qtd")[:5]
        )
        por_evento_labels = [row["nome"] for row in por_evento]
        por_evento_values = [int(row["qtd"]) for row in por_evento]
    else:
        por_evento_labels, por_evento_values = [], []

    # =========================
    #   GRÃƒÂFICO: STATUS DE PAGAMENTO
    # =========================
    # Vamos montar: confirmadas, pendentes e (se existir) canceladas
    confirmadas = total_inscricoes_confirmadas
    canceladas = 0
    if _model_has_field(Inscricao, "cancelada"):
        canceladas = insc_qs.filter(cancelada=True).count()
    elif _model_has_field(Inscricao, "status"):
        canceladas = insc_qs.filter(status__iexact="cancelada").count()

    pendentes = max(total_inscricoes - confirmadas - canceladas, 0)

    pagamentos_status_values = {
        "confirmadas": confirmadas,
        "pendentes": pendentes,
        "canceladas": canceladas,
    }

    # =========================
    #   GRÃƒÂFICO: CONVERSÃƒÆ’O (inscritos x confirmados)
    # =========================
    conversao_values = {
        "inscritos": total_inscricoes,
        "confirmados": confirmadas,
    }

    # =========================
    #   CONTEXTO + JSON SAFE
    # =========================
    ctx = {
        "paroquia": paroquia,
        "eventos": eventos,
        "is_admin_paroquia": is_admin_paroquia,
        "is_admin_geral": is_admin_geral,

        # KPIs reais
        "eventos_abertos": eventos_abertos,
        "total_inscricoes": total_inscricoes,
        "total_inscricoes_confirmadas": total_inscricoes_confirmadas,
        "pendencias_contagem": pendentes,

        # SÃƒÂ©ries/GrÃƒÂ¡ficos (jÃƒÂ¡ como JSON seguro p/ template)
        "inscricoes_dias_labels": mark_safe(json.dumps(labels_dias)),
        "inscricoes_dias_values": mark_safe(json.dumps(values_dias)),
        "inscricoes_por_evento_labels": mark_safe(json.dumps(por_evento_labels)),
        "inscricoes_por_evento_values": mark_safe(json.dumps(por_evento_values)),
        "pagamentos_status_values": mark_safe(json.dumps(pagamentos_status_values)),
        "conversao_values": mark_safe(json.dumps(conversao_values)),
    }

    return render(request, "inscricoes/admin_paroquia_painel.html", ctx)

from typing import Optional
import json
from datetime import timedelta, date

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, F, IntegerField
from django.db.models.functions import Coalesce, TruncDate
from django.core.exceptions import FieldError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

@login_required
def evento_novo(request):
    if request.method == 'POST':
        form = EventoForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            evento = form.save(commit=False)
            if hasattr(request.user, 'paroquia') and request.user.paroquia:
                evento.paroquia = request.user.paroquia
            elif not evento.paroquia:
                messages.error(request, 'Selecione uma parÃƒÂ³quia para o evento.')
                return render(request, 'inscricoes/evento_form.html', {'form': form})

            evento.save()
            messages.success(request, 'Evento criado com sucesso!')
            return redirect('inscricoes:admin_paroquia_painel')
    else:
        form = EventoForm(user=request.user)

    return render(request, 'inscricoes/evento_form.html', {'form': form})


@login_required
def eventos_listar(request):
    # sua lÃƒÂ³gica
    pass

@login_required
def inscricoes_listar(request):
    # cÃƒÂ³digo para listar inscriÃƒÂ§ÃƒÂµes
    pass

@login_required
@require_http_methods(["GET", "POST"])
def evento_editar(request, pk):
    """Editar evento (pk ÃƒÂ© UUID)."""
    evento = get_object_or_404(EventoAcampamento, pk=pk)

    # PermissÃƒÂ£o: admin da MESMA parÃƒÂ³quia ou admin geral
    if not request.user.is_superuser:
        if not hasattr(request.user, "paroquia") or request.user.paroquia_id != evento.paroquia_id:
            return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para editar este evento.")

    if request.method == "POST":
        form = EventoForm(request.POST, request.FILES, instance=evento, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Evento atualizado com sucesso!")
            # redireciona para o painel da parÃƒÂ³quia correta
            if hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral():
                return redirect("inscricoes:admin_paroquia_painel", paroquia_id=evento.paroquia_id)
            return redirect("inscricoes:admin_paroquia_painel")
    else:
        form = EventoForm(instance=evento, user=request.user)

    return render(request, "inscricoes/evento_form.html", {"form": form, "evento": evento})


@login_required
@require_http_methods(["GET", "POST"])
def evento_deletar(request, pk):
    """Confirma e deleta o evento (pk ÃƒÂ© UUID)."""
    evento = get_object_or_404(EventoAcampamento, pk=pk)

    # PermissÃƒÂ£o: admin da MESMA parÃƒÂ³quia ou admin geral
    if not request.user.is_superuser:
        if not hasattr(request.user, "paroquia") or request.user.paroquia_id != evento.paroquia_id:
            return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para excluir este evento.")

    if request.method == "POST":
        nome = evento.nome
        paroquia_id = evento.paroquia_id
        evento.delete()
        messages.success(request, f"Evento Ã‚â€œ{nome}Ã‚â€ excluÃƒÂ­do com sucesso.")

        # Volta para o painel apropriado
        if hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral():
            return redirect("inscricoes:admin_paroquia_painel", paroquia_id=paroquia_id)
        return redirect("inscricoes:admin_paroquia_painel")

    # GET: mostra a pÃƒÂ¡gina de confirmaÃƒÂ§ÃƒÂ£o
    return render(request, "inscricoes/evento_confirm_delete.html", {"obj": evento, "tipo": "Evento"})


def inscricao_evento_publico(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # Aqui vocÃƒÂª pode colocar lÃƒÂ³gica para mostrar o formulÃƒÂ¡rio de inscriÃƒÂ§ÃƒÂ£o, dados do evento, etc.
    context = {
        'evento': evento,
    }
    return render(request, 'inscricoes/evento_publico.html', context)

from .models import PoliticaPrivacidade


from .utils.eventos import tipo_efetivo_evento

def ver_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)

    passos = [
        'InscriÃƒÂ§ÃƒÂ£o enviada',
        'SeleÃƒÂ§ÃƒÂ£o do participante',
        'Pagamento confirmado',
        'ParticipaÃƒÂ§ÃƒÂ£o confirmada',
    ]

    if inscricao.inscricao_concluida:
        inscricao_status = 4
    elif inscricao.pagamento_confirmado:
        inscricao_status = 3
    elif inscricao.foi_selecionado:
        inscricao_status = 2
    else:
        inscricao_status = 1

    politica = PoliticaPrivacidade.objects.first()

    # --- tipo efetivo cobre "servos vinculado a casais" ---
    tipo_efetivo = tipo_efetivo_evento(inscricao.evento)

    # --- Nome secundÃƒÂ¡rio (cÃƒÂ´njuge ou inscriÃƒÂ§ÃƒÂ£o pareada) ---
    secundario_nome = None

    # Caso "casais" (efeito: casais mesmo, ou servos?casais)
    if tipo_efetivo == "casais":
        # 1) Se houver objeto Conjuge ligado ÃƒÂ  inscriÃƒÂ§ÃƒÂ£o, usa
        try:
            conj = getattr(inscricao, "conjuge", None)
            if conj and (conj.nome or "").strip():
                secundario_nome = conj.nome.strip()
        except Exception:
            pass

        # 2) Se nÃƒÂ£o houver, tenta inscriÃƒÂ§ÃƒÂ£o pareada
        if not secundario_nome:
            pareada = getattr(inscricao, "inscricao_pareada", None) or getattr(inscricao, "pareada_por", None)
            if pareada and getattr(pareada, "participante", None):
                nome_pareado = getattr(pareada.participante, "nome", "") or ""
                if nome_pareado.strip():
                    secundario_nome = nome_pareado.strip()

    context = {
        'inscricao': inscricao,
        'passos': passos,
        'inscricao_status': inscricao_status,
        'evento': inscricao.evento,
        'politica': politica,
        'tipo_efetivo': tipo_efetivo,
        'secundario_nome': secundario_nome,
    }
    return render(request, 'inscricoes/ver_inscricao.html', context)


from .forms import InscricaoForm
from .forms import ParticipanteForm
from django.forms import modelformset_factory
from django.forms import inlineformset_factory

@login_required
def editar_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)
    participante = inscricao.participante

    # Form específico por tipo
    tipo_evento = (inscricao.evento.tipo or '').lower()
    base_form_class = {
        'senior':  InscricaoSeniorForm,
        'juvenil': InscricaoJuvenilForm,
        'mirim':   InscricaoMirimForm,
        'servos':  InscricaoServosForm,
    }.get(tipo_evento)

    base_instance = None
    if base_form_class:
        base_model = base_form_class._meta.model
        base_instance = base_model.objects.filter(inscricao=inscricao).first()

    conjuge_instance = getattr(inscricao, 'conjuge', None)
    pagamento_instance = Pagamento.objects.filter(inscricao=inscricao).first()

    # ---- Contatos: usar INLINE formset (filhos de Inscricao) ----
    ContatoFormSet = inlineformset_factory(
        parent_model=Inscricao,
        model=Contato,
        form=ContatoForm,        # ModelForm (ver abaixo)
        extra=0,
        can_delete=True
        # você pode colocar fields=([...]) ou exclude=('inscricao',) no ContatoForm
    )

    if request.method == 'POST':
        inscricao_form    = InscricaoForm(request.POST, request.FILES, instance=inscricao, evento=inscricao.evento)
        participante_form = ParticipanteForm(request.POST, request.FILES, instance=participante)
        base_form         = base_form_class(request.POST, request.FILES, instance=base_instance) if base_form_class else None
        conjuge_form      = ConjugeForm(request.POST, request.FILES, instance=conjuge_instance) if conjuge_instance else None
        contato_formset   = ContatoFormSet(request.POST, request.FILES, instance=inscricao)
        pagamento_form    = PagamentoForm(request.POST, request.FILES, instance=pagamento_instance) if pagamento_instance else None

        forms_ok = (
            inscricao_form.is_valid()
            and participante_form.is_valid()
            and (base_form.is_valid() if base_form else True)
            and (conjuge_form.is_valid() if conjuge_form else True)
            and contato_formset.is_valid()
            and (pagamento_form.is_valid() if pagamento_form else True)
        )

        if forms_ok:
            with transaction.atomic():
                inscricao_form.save()
                participante_form.save()
                if base_form: base_form.save()
                if conjuge_form: conjuge_form.save()
                contato_formset.save()  # inline formset cuida de criar/atualizar/deletar e seta FK
                if pagamento_form: pagamento_form.save()

            messages.success(request, "Inscrição atualizada com sucesso!")
            return redirect('inscricoes:inscricao_ficha_geral', pk=inscricao.pk)

        # debug de erros (opcional)
        def dump(label, f):
            if hasattr(f, 'errors') and f.errors:
                messages.error(request, f"[{label}] {f.errors.as_text()}")
        dump("Inscrição", inscricao_form)
        dump("Participante", participante_form)
        if base_form:   dump("Específico", base_form)
        if conjuge_form: dump("Cônjuge", conjuge_form)
        if pagamento_form: dump("Pagamento", pagamento_form)
        if contato_formset.non_form_errors():
            messages.error(request, f"[Contatos] {contato_formset.non_form_errors()}")

    else:
        inscricao_form    = InscricaoForm(instance=inscricao, evento=inscricao.evento)
        participante_form = ParticipanteForm(instance=participante)
        base_form         = base_form_class(instance=base_instance) if base_form_class else None
        conjuge_form      = ConjugeForm(instance=conjuge_instance) if conjuge_instance else None
        contato_formset   = ContatoFormSet(instance=inscricao)
        pagamento_form    = PagamentoForm(instance=pagamento_instance) if pagamento_instance else None

    return render(request, 'inscricoes/editar_inscricao.html', {
        'inscricao': inscricao,
        'inscricao_form': inscricao_form,
        'participante_form': participante_form,
        'base_form': base_form,
        'conjuge_form': conjuge_form,
        'contato_formset': contato_formset,  # <- use esse nome no template
        'pagamento_form': pagamento_form,
    })


@login_required
def deletar_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)

    if request.method == 'POST':
        evento_id = inscricao.evento.id
        inscricao.delete()
        return redirect('inscricoes:evento_participantes', evento_id=evento_id)

    return render(request, 'inscricoes/confirma_delecao.html', {'obj': inscricao})

@login_required
def ficha_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)
    evento = inscricao.evento

    # Mapeia tipo -> nome do related OneToOne na Inscricao
    rel_por_tipo = {
        'senior':  'inscricaosenior',
        'juvenil': 'inscricaojuvenil',
        'mirim':   'inscricaomirim',
        'servos':  'inscricaoservos',
        'casais':  'inscricaocasais',
        'evento':  'inscricaoevento',
        'retiro':  'inscricaoretiro',
    }

    # tenta primeiro a relaÃƒÂ§ÃƒÂ£o "preferida" pelo tipo do evento; depois faz fallback em todas
    tipo = (getattr(evento, 'tipo', '') or '').lower()
    nomes = []
    preferida = rel_por_tipo.get(tipo)
    if preferida:
        nomes.append(preferida)
    nomes += [
        'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
        'inscricaocasais', 'inscricaoevento', 'inscricaoretiro'
    ]

    base = None
    seen = set()
    for name in [n for n in nomes if n and n not in seen]:
        seen.add(name)
        obj = getattr(inscricao, name, None)
        if obj:
            base = obj
            break

    # Data de nascimento (com fallback no Participante, se existir lÃƒÂ¡)
    data_nascimento = getattr(base, 'data_nascimento', None) or getattr(inscricao.participante, 'data_nascimento', None)

    return render(request, 'inscricoes/ficha_inscricao.html', {
        'inscricao': inscricao,
        'inscricao_base': base,           # pode ser None se ainda nÃƒÂ£o preencheram a ficha
        'data_nascimento': data_nascimento,
    })


@login_required
def imprimir_cracha(request, pk):
    insc = get_object_or_404(
        Inscricao.objects.select_related(
            "participante", "evento",
            "inscricaocasais",
            "alocacao_grupo__grupo",
            "alocacao_ministerio",
        ),
        pk=pk,
    )

    # Resolve "par" (casal/pareado/conjuge) se existir
    par = None
    for attr in ("inscricao_pareada", "pareada_por", "conjuge"):
        if hasattr(insc, attr):
            obj = getattr(insc, attr)
            if obj:
                par = obj
                break

    # casal/servo-casais?
    tipo = (getattr(insc.evento, "tipo", "") or "").lower()
    is_casais = (tipo == "casais")
    is_servos_casais = (tipo == "servos") and (
        getattr(insc, "inscricaocasais", None) or (par and getattr(par, "inscricaocasais", None))
    )
    couple_mode = bool(par) and (is_casais or is_servos_casais)

    context = {
        "inscricao": insc,
        "par": par,                 # usado pelo template
        "couple_mode": couple_mode, # diz se deve mostrar "Fulano — Sicrano"
    }
    return render(request, "inscricoes/imprimir_cracha.html", context)

def incluir_pagamento(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    metodo_choices = Pagamento.MetodoPagamento.choices
    valor_default = inscricao.evento.valor_inscricao
    metodo_selecionado = None

    if request.method == 'POST':
        valor = request.POST.get('valor')
        metodo = request.POST.get('metodo')
        comprovante = request.FILES.get('comprovante')  # captura arquivo enviado

        erros = []

        # ValidaÃƒÂ§ÃƒÂ£o valor
        if not valor:
            erros.append('O valor ÃƒÂ© obrigatÃƒÂ³rio.')
        else:
            try:
                valor_decimal = float(valor)
                if valor_decimal <= 0:
                    erros.append('O valor deve ser maior que zero.')
            except ValueError:
                erros.append('Valor invÃƒÂ¡lido.')

        # ValidaÃƒÂ§ÃƒÂ£o mÃƒÂ©todo
        if metodo not in [choice[0] for choice in metodo_choices]:
            erros.append('MÃƒÂ©todo de pagamento invÃƒÂ¡lido.')

        if erros:
            for erro in erros:
                messages.error(request, erro)
            metodo_selecionado = metodo  # para manter selecionado no form
        else:
            pagamento, created = Pagamento.objects.update_or_create(
                inscricao=inscricao,
                defaults={
                    'valor': valor_decimal,
                    'metodo': metodo,
                    'status': Pagamento.StatusPagamento.CONFIRMADO,
                    'data_pagamento': dj_tz.now(),
                }
            )
            # Se enviou comprovante, salva no campo (substitui se jÃƒÂ¡ tinha)
            if comprovante:
                pagamento.comprovante = comprovante
                pagamento.save()

            # Marca a inscriÃƒÂ§ÃƒÂ£o como pagamento confirmado
            if not inscricao.pagamento_confirmado:
                inscricao.pagamento_confirmado = True
                inscricao.save()

            messages.success(request, 'Pagamento incluÃƒÂ­do com sucesso!')
            return redirect('inscricoes:evento_participantes', evento_id=inscricao.evento.id)

    else:
        # GET: tenta carregar pagamento existente para preencher formulÃƒÂ¡rio
        try:
            pagamento = Pagamento.objects.get(inscricao=inscricao)
            valor_default = pagamento.valor
            metodo_selecionado = pagamento.metodo
        except Pagamento.DoesNotExist:
            metodo_selecionado = None

    return render(request, 'inscricoes/incluir_pagamento.html', {
        'inscricao': inscricao,
        'metodo_choices': metodo_choices,
        'valor_default': valor_default,
        'metodo_selecionado': metodo_selecionado,
        # Passa o pagamento para mostrar comprovante atual, se quiser
        'pagamento': Pagamento.objects.filter(inscricao=inscricao).first(),
    })

def inscricao_inicial(request, slug):
    import re

    def _digits(s: str | None) -> str:
        return re.sub(r'\D', '', s or '')

    def _fmt_cpf(d: str) -> str:
        return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d) == 11 else d

    evento = get_object_or_404(EventoAcampamento, slug=slug)
    politica = PoliticaPrivacidade.objects.first()
    hoje = dj_tz.localdate()

    # Usa o tipo efetivo (pode Ã‚â€œvirarÃ‚â€ casais quando servos vinculado a casais)
    tipo_eff = _tipo_formulario_evento(evento)
    is_casais = (tipo_eff == 'casais')

    # Fora do perÃƒÂ­odo?
    if hoje < evento.inicio_inscricoes or hoje > evento.fim_inscricoes:
        return render(request, 'inscricoes/inscricao_encerrada.html', {
            'evento': evento,
            'politica': politica
        })

    # ===================== FLUXO "PAGAMENTO" ===================== #
    if (tipo_eff or '').lower() == 'pagamento':
        form = FormBasicoPagamentoPublico(request.POST or None)

        if request.method == 'POST' and form.is_valid():
            # Participante 1
            nome1  = (form.cleaned_data.get('nome') or '').strip()
            cpf1   = _digits(form.cleaned_data.get('cpf') or request.POST.get('cpf') or '')
            # Participante 2 (opcional)
            nome2  = (form.cleaned_data.get('nome_segundo') or '').strip()
            cpf2   = _digits(form.cleaned_data.get('cpf_segundo') or request.POST.get('cpf_segundo') or '')
            # Comum
            cidade = (form.cleaned_data.get('cidade') or '').strip()

            erros = []
            if len(cpf1) != 11:
                erros.append("Informe um CPF vÃƒÂ¡lido (11 dÃƒÂ­gitos) para o 1Ã‚Âº participante.")
            if cpf2 and len(cpf2) != 11:
                erros.append("Informe um CPF vÃƒÂ¡lido (11 dÃƒÂ­gitos) para o 2Ã‚Âº participante.")
            if erros:
                for e in erros:
                    messages.error(request, e)
                return render(request, 'inscricoes/form_basico_pagamento.html', {
                    'form': form, 'evento': evento, 'politica': politica
                })

            # -------- Participante 1 --------
            p1, _ = Participante.objects.get_or_create(
                cpf=cpf1,
                defaults={'nome': nome1, 'cidade': cidade}
            )
            mudou1 = False
            if nome1 and (p1.nome or '').strip() != nome1:
                p1.nome = nome1; mudou1 = True
            if cidade and (getattr(p1, 'cidade', '') or '').strip() != cidade:
                p1.cidade = cidade; mudou1 = True
            if mudou1:
                p1.save()

            i1, _ = Inscricao.objects.get_or_create(
                participante=p1, evento=evento,
                defaults={'paroquia': evento.paroquia}
            )
            if not i1.foi_selecionado:
                i1.foi_selecionado = True
                i1.save(update_fields=['foi_selecionado'])

            Pagamento.objects.update_or_create(
                inscricao=i1,
                defaults={
                    'valor': float(evento.valor_inscricao or 0),
                    'status': Pagamento.StatusPagamento.PENDENTE,
                    'metodo': Pagamento.MetodoPagamento.PIX,  # ajuste se necessÃƒÂ¡rio
                }
            )

            # -------- Participante 2 (opcional) --------
            if cpf2:
                p2, created2 = Participante.objects.get_or_create(
                    cpf=cpf2,
                    defaults={'nome': nome2, 'cidade': cidade}
                )
                mudou2 = False
                if nome2 and (p2.nome or '').strip() != nome2:
                    p2.nome = nome2; mudou2 = True
                if cidade and (getattr(p2, 'cidade', '') or '').strip() != cidade:
                    p2.cidade = cidade; mudou2 = True
                if mudou2:
                    p2.save()

                i2, _ = Inscricao.objects.get_or_create(
                    participante=p2, evento=evento,
                    defaults={'paroquia': evento.paroquia}
                )
                if not i2.foi_selecionado:
                    i2.foi_selecionado = True
                    i2.save(update_fields=['foi_selecionado'])

                Pagamento.objects.update_or_create(
                    inscricao=i2,
                    defaults={
                        'valor': float(evento.valor_inscricao or 0),
                        'status': Pagamento.StatusPagamento.PENDENTE,
                        'metodo': Pagamento.MetodoPagamento.PIX,
                    }
                )

                # Parear se o modelo tiver o campo
                if hasattr(i1, 'inscricao_pareada') and not i1.inscricao_pareada_id:
                    i1.inscricao_pareada = i2
                    i1.save(update_fields=['inscricao_pareada'])
                if hasattr(i2, 'inscricao_pareada') and not i2.inscricao_pareada_id:
                    i2.inscricao_pareada = i1
                    i2.save(update_fields=['inscricao_pareada'])

            messages.success(request, "InscriÃƒÂ§ÃƒÂ£o(ÃƒÂµes) criada(s) e pagamento(s) marcado(s) como pendente(s).")
            return redirect('inscricoes:ver_inscricao', pk=i1.id)

        # GET ou invÃƒÂ¡lido
        return render(request, 'inscricoes/form_basico_pagamento.html', {
            'form': form, 'evento': evento, 'politica': politica
        })
    # =================== FIM FLUXO "PAGAMENTO" =================== #

    # Para 'casais' (inclusive servos->casais)
    if is_casais:
        return redirect('inscricoes:formulario_casais', evento_id=evento.id)

    # --- Retomar endereÃƒÂ§o ---
    if request.GET.get("retomar") == "1" and request.GET.get("pid"):
        try:
            participante_id = int(request.GET["pid"])
            participante = Participante.objects.get(id=participante_id)
            Inscricao.objects.get(participante=participante, evento=evento)
            request.session["participante_id"] = participante.id
        except (ValueError, Participante.DoesNotExist, Inscricao.DoesNotExist):
            pass

    # --- Etapa endereÃƒÂ§o ---
    if 'participante_id' in request.session:
        endereco_form = ParticipanteEnderecoForm(request.POST or None)
        if request.method == 'POST' and endereco_form.is_valid():
            participante = Participante.objects.get(id=request.session['participante_id'])
            participante.CEP = endereco_form.cleaned_data['CEP']
            participante.endereco = endereco_form.cleaned_data['endereco']
            participante.numero = endereco_form.cleaned_data['numero']
            participante.bairro = endereco_form.cleaned_data['bairro']
            participante.cidade = endereco_form.cleaned_data['cidade']
            participante.estado = endereco_form.cleaned_data['estado']
            participante.save()

            inscricao = Inscricao.objects.get(participante=participante, evento=evento)

            del request.session['participante_id']
            return redirect('inscricoes:formulario_personalizado', inscricao_id=inscricao.id)

        return render(request, 'inscricoes/inscricao_inicial.html', {
            'endereco_form': endereco_form,
            'evento': evento,
            'politica': politica,
            'is_casais': is_casais,
        })

    # --- Etapa inicial padrÃƒÂ£o ---
    inicial_form = ParticipanteInicialForm(request.POST or None)
    if request.method == 'POST' and inicial_form.is_valid():
        cpf = _digits(inicial_form.cleaned_data['cpf'])
        participante, created = Participante.objects.get_or_create(
            cpf=cpf,
            defaults={
                'nome': inicial_form.cleaned_data['nome'],
                'email': inicial_form.cleaned_data['email'],
                'telefone': inicial_form.cleaned_data['telefone']
            }
        )
        if not created:
            participante.nome = inicial_form.cleaned_data['nome']
            participante.email = inicial_form.cleaned_data['email']
            participante.telefone = inicial_form.cleaned_data['telefone']
            participante.save()

        request.session['participante_id'] = participante.id

        inscricao, _ = Inscricao.objects.get_or_create(
            participante=participante, evento=evento, paroquia=evento.paroquia
        )

        prog = _proxima_etapa_forms(inscricao)
        if prog and prog.get("next_url"):
            return redirect(prog["next_url"])

        return redirect('inscricoes:ver_inscricao', pk=inscricao.id)

    return render(request, 'inscricoes/inscricao_inicial.html', {
        'form': inicial_form,
        'evento': evento,
        'politica': politica,
        'is_casais': is_casais,
    })

# inscricoes/views_ajax.py  (ou no seu views.py, se preferir)
import re
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.db.models import Q

from .models import Participante, Inscricao

def _digits(s: str | None) -> str:
    return re.sub(r'\D', '', s or '')

def _fmt_cpf(d: str) -> str:
    return f"{d[0:3]}.{d[3:6]}.{d[6:9]}-{d[9:11]}" if len(d) == 11 else d

@require_GET
def ajax_buscar_conjuge(request):
    """
    GET /ajax/buscar-conjuge/?cpf=XXXXXXXXXXX&evento_id=UUID
    Retorna:
      { ok: bool, nome: str|None, participante_id: int|None,
        inscricao_id: int|None }
    """
    cpf = _digits(request.GET.get('cpf'))
    evento_id = request.GET.get('evento_id')

    if len(cpf) != 11:
        return JsonResponse({'ok': False, 'erro': 'cpf_invalido'})

    # tenta achar participante por CPF em ambas formas (com/sem mÃƒÂ¡scara)
    possiveis_cpfs = {_fmt_cpf(cpf), cpf}

    p = Participante.objects.filter(cpf__in=possiveis_cpfs).first()
    if not p:
        # nÃƒÂ£o tem cadastro ainda Ã‚â€” ok (nÃƒÂ£o bloqueia)
        return JsonResponse({'ok': True, 'nome': None, 'participante_id': None, 'inscricao_id': None})

    payload = {'ok': True, 'nome': p.nome, 'participante_id': p.id, 'inscricao_id': None}

    if evento_id:
        insc = Inscricao.objects.filter(evento_id=evento_id, participante=p).first()
        if insc:
            payload['inscricao_id'] = insc.id

    return JsonResponse(payload)


def buscar_participante_ajax(request):
    cpf = (request.GET.get('cpf') or '').replace('.', '').replace('-', '')
    evento_id = request.GET.get('evento_id')

    try:
        participante = Participante.objects.get(cpf=cpf)
    except Participante.DoesNotExist:
        return JsonResponse({'ja_inscrito': False})

    # Tenta achar a inscriÃƒÂ§ÃƒÂ£o deste evento
    inscricao = None
    if evento_id:
        inscricao = Inscricao.objects.filter(participante=participante, evento_id=evento_id).first()

    # Se NÃƒÆ’O tem inscriÃƒÂ§ÃƒÂ£o neste evento ? devolve dados p/ autopreencher
    if not inscricao:
        return JsonResponse({
            'ja_inscrito': False,          # compat com front antigo
            'existe_participante': True,
            'status': 'sem_inscricao',
            'nome': participante.nome or '',
            'email': participante.email or '',
            'telefone': participante.telefone or '',
        })

    # JÃƒÂ¡ existe inscriÃƒÂ§ÃƒÂ£o Ã‚â€” calcular prÃƒÂ³xima etapa
    prog = _proxima_etapa_forms(inscricao)
    payload = {
        'ja_inscrito': inscricao.inscricao_enviada,  # compat: sÃƒÂ³ "True" quando jÃƒÂ¡ enviada
        'existe_participante': True,
        'inscricao_id': inscricao.id,
        'view_url': reverse('inscricoes:ver_inscricao', args=[inscricao.id]),
        'status': 'concluida' if inscricao.pagamento_confirmado else (
            'enviada' if inscricao.inscricao_enviada else 'em_andamento'
        ),
        'progresso': prog,  # {'step': ..., 'next_url': ...}
        'nome': participante.nome or '',
        'email': participante.email or '',
        'telefone': participante.telefone or '',
    }
    return JsonResponse(payload)



def formulario_personalizado(request, inscricao_id):
    # ObtÃƒÂ©m a inscriÃƒÂ§ÃƒÂ£o, evento e polÃƒÂ­tica de privacidade
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    politica = PoliticaPrivacidade.objects.first()

    # Mapeia tipo de evento ? (FormClass, atributo OneToOne na Inscricao)
    form_map = {
        'senior':  (InscricaoSeniorForm,  'inscricaosenior'),
        'juvenil': (InscricaoJuvenilForm, 'inscricaojuvenil'),
        'mirim':   (InscricaoMirimForm,   'inscricaomirim'),
        'servos':  (InscricaoServosForm,  'inscricaoservos'),
        'casais':  (InscricaoCasaisForm,  'inscricaocasais'),
        'evento':  (InscricaoEventoForm,  'inscricaoevento'),
        'retiro':  (InscricaoRetiroForm,  'inscricaoretiro'),
    }

    # usa o tipo efetivo (servos->casais quando vinculado)
    tipo_eff = _tipo_formulario_evento(evento)
    if tipo_eff not in form_map:
        raise Http404("Tipo de evento invÃƒÂ¡lido.")

    FormClass, rel_name = form_map[tipo_eff]
    instancia = getattr(inscricao, rel_name, None)
    conj_inst = getattr(inscricao, 'conjuge', None)  # pode existir de eventos casais

    if request.method == 'POST':
        form = FormClass(request.POST, request.FILES, instance=instancia)
        conj_form = ConjugeForm(request.POST, instance=conj_inst) if tipo_eff == "casais" else None

        # validaÃƒÂ§ÃƒÂ£o: cÃƒÂ´njuge sÃƒÂ³ ÃƒÂ© obrigatÃƒÂ³rio para casais
        if form.is_valid() and (tipo_eff != "casais" or (conj_form and conj_form.is_valid())):
            # Salva dados do formulÃƒÂ¡rio principal
            obj = form.save(commit=False)
            obj.inscricao = inscricao
            obj.paroquia = inscricao.paroquia  # se seu modelo possui campo paroquia
            obj.save()

            # Salva dados do CÃƒÂ´njuge (apenas para 'casais' efetivo)
            if tipo_eff == "casais":
                conj = conj_form.save(commit=False)
                conj.inscricao = inscricao
                conj.save()

            return redirect('inscricoes:formulario_contato', inscricao_id=inscricao.id)
    else:
        form = FormClass(instance=instancia)
        conj_form = ConjugeForm(instance=conj_inst) if tipo_eff == "casais" else None

    # Campos condicionais controlados via JS
    campos_condicionais = [
        # Participante principal
        'ja_e_campista',
        'tema_acampamento',

        # CÃƒÂ´njuge (apenas quando casais efetivo)
        'nome_conjuge',
        'conjuge_inscrito',
        'ja_e_campista_conjuge',
        'tema_acampamento_conjuge',

        # Casado/uniÃƒÂ£o estÃƒÂ¡vel
        'estado_civil',
        'tempo_casado_uniao',
        'casado_na_igreja',
    ]

    exibir_conjuge = (tipo_eff == 'casais')

    return render(request, 'inscricoes/formulario_personalizado.html', {
        'form': form,
        'conj_form': conj_form,
        'inscricao': inscricao,
        'evento': evento,
        'campos_condicionais': campos_condicionais,
        'politica': politica,
        'exibir_conjuge': exibir_conjuge,
    })

@require_POST
def evento_toggle_servos(request, pk):
    ev = get_object_or_404(EventoAcampamento, pk=pk)

    # SÃƒÂ³ faz sentido no PRINCIPAL (nÃƒÂ£o no prÃƒÂ³prio evento de servos)
    if (ev.tipo or "").lower() == "servos":
        return JsonResponse({"ok": False, "msg": "AÃƒÂ§ÃƒÂ£o permitida apenas no evento principal."}, status=400)

    permitir = (request.POST.get("permitir") or "").lower() in ("1", "true", "on", "yes", "sim")
    ev.permitir_inscricao_servos = permitir
    ev.save(update_fields=["permitir_inscricao_servos"])

    msg = "InscriÃƒÂ§ÃƒÂµes de servos ativadas." if permitir else "InscriÃƒÂ§ÃƒÂµes de servos desativadas."
    return JsonResponse({"ok": True, "permitir": permitir, "msg": msg})


from django.forms import modelformset_factory
from .models import Filho
from .forms import ContatoForm, FilhoForm

from django.shortcuts import render, get_object_or_404, redirect
from django.forms import modelformset_factory
from .models import Inscricao, PoliticaPrivacidade, Filho
from .forms import ContatoForm, FilhoForm


def formulario_contato(request, inscricao_id):
    # Recupera a inscriÃƒÂ§ÃƒÂ£o
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Evento e polÃƒÂ­tica
    evento = inscricao.evento
    politica = PoliticaPrivacidade.objects.first()

    # SÃƒÂ³ cria formset de filhos se for evento de casais
    filhos_formset = None
    filhos_qs = Filho.objects.none()
    if evento.tipo == "casais":
        FilhoFormSet = modelformset_factory(Filho, form=FilhoForm, extra=8, can_delete=True)
        filhos_qs = Filho.objects.filter(inscricao=inscricao)

    if request.method == 'POST':
        form = ContatoForm(request.POST)

        if evento.tipo == "casais":
            filhos_formset = FilhoFormSet(request.POST, queryset=filhos_qs)
        else:
            filhos_formset = None

        if form.is_valid() and (not filhos_formset or filhos_formset.is_valid()):
            # Atualiza os dados da inscriÃƒÂ§ÃƒÂ£o
            inscricao.responsavel_1_nome = form.cleaned_data['responsavel_1_nome']
            inscricao.responsavel_1_telefone = form.cleaned_data['responsavel_1_telefone']
            inscricao.responsavel_1_grau_parentesco = form.cleaned_data['responsavel_1_grau_parentesco']
            inscricao.responsavel_1_ja_e_campista = form.cleaned_data['responsavel_1_ja_e_campista']

            inscricao.responsavel_2_nome = form.cleaned_data['responsavel_2_nome']
            inscricao.responsavel_2_telefone = form.cleaned_data['responsavel_2_telefone']
            inscricao.responsavel_2_grau_parentesco = form.cleaned_data['responsavel_2_grau_parentesco']
            inscricao.responsavel_2_ja_e_campista = form.cleaned_data['responsavel_2_ja_e_campista']

            inscricao.contato_emergencia_nome = form.cleaned_data['contato_emergencia_nome']
            inscricao.contato_emergencia_telefone = form.cleaned_data['contato_emergencia_telefone']
            inscricao.contato_emergencia_grau_parentesco = form.cleaned_data['contato_emergencia_grau_parentesco']
            inscricao.contato_emergencia_ja_e_campista = form.cleaned_data['contato_emergencia_ja_e_campista']

            inscricao.save()

            # Salva filhos (apenas se evento for casais)
            if filhos_formset:
                filhos = filhos_formset.save(commit=False)
                for filho in filhos:
                    filho.inscricao = inscricao
                    filho.save()
                for f in filhos_formset.deleted_objects:
                    f.delete()

            return redirect('inscricoes:formulario_saude', inscricao_id=inscricao.id)

    else:
        # PrÃƒÂ©-popula formulÃƒÂ¡rio
        form = ContatoForm(initial={
            'responsavel_1_nome': inscricao.responsavel_1_nome,
            'responsavel_1_telefone': inscricao.responsavel_1_telefone,
            'responsavel_1_grau_parentesco': inscricao.responsavel_1_grau_parentesco,
            'responsavel_1_ja_e_campista': inscricao.responsavel_1_ja_e_campista,
            'responsavel_2_nome': inscricao.responsavel_2_nome,
            'responsavel_2_telefone': inscricao.responsavel_2_telefone,
            'responsavel_2_grau_parentesco': inscricao.responsavel_2_grau_parentesco,
            'responsavel_2_ja_e_campista': inscricao.responsavel_2_ja_e_campista,
            'contato_emergencia_nome': inscricao.contato_emergencia_nome,
            'contato_emergencia_telefone': inscricao.contato_emergencia_telefone,
            'contato_emergencia_grau_parentesco': inscricao.contato_emergencia_grau_parentesco,
            'contato_emergencia_ja_e_campista': inscricao.contato_emergencia_ja_e_campista,
        })

        if evento.tipo == "casais":
            filhos_formset = FilhoFormSet(queryset=filhos_qs)

    return render(request, 'inscricoes/formulario_contato.html', {
        'form': form,
        'filhos_formset': filhos_formset,  # pode ser None se nÃƒÂ£o for casais
        'inscricao': inscricao,
        'evento': evento,
        'politica': politica,
        'range_filhos': range(1, 9),  # para o select do template
        'filhos_qs': filhos_qs,
    })



def formulario_saude(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    participante = inscricao.participante
    politica = PoliticaPrivacidade.objects.first()

    # Mapeia tipo ? modelo correto da BaseInscricao (inclui novos tipos)
    model_map = {
        'senior': InscricaoSenior,
        'juvenil': InscricaoJuvenil,
        'mirim':  InscricaoMirim,
        'servos': InscricaoServos,
        'casais': InscricaoCasais,   # NOVO
        'evento': InscricaoEvento,   # NOVO
        'retiro': InscricaoRetiro,   # NOVO
    }
    tipo = (evento.tipo or '').lower()
    Model = model_map.get(tipo)
    if not Model:
        raise Http404("Tipo de evento invÃƒÂ¡lido.")

    # Garante que a base exista (evita 404 quando ainda nÃƒÂ£o foi criada)
    base_inscricao, _ = Model.objects.get_or_create(
        inscricao=inscricao,
        defaults={'paroquia': inscricao.paroquia}
    )

    # Cria um ModelForm dinÃƒÂ¢mico reusando seu DadosSaudeForm (mesmos campos/validaÃƒÂ§ÃƒÂµes)
    SaudeForm = modelform_factory(
        Model,
        form=DadosSaudeForm,
        fields=DadosSaudeForm.Meta.fields
    )

    if request.method == 'POST':
        form_saude = SaudeForm(request.POST, request.FILES, instance=base_inscricao)

        # DecisÃƒÂ£o do modal de consentimento (input hidden no template)
        consent_ok = (request.POST.get('consentimento_envio') == 'sim')
        if not consent_ok:
            form_saude.add_error(None, "VocÃƒÂª precisa aceitar a PolÃƒÂ­tica de Privacidade para enviar a inscriÃƒÂ§ÃƒÂ£o.")

        if form_saude.is_valid():
            # Salva os campos do modelo (a 'foto' ÃƒÂ© extra de formulÃƒÂ¡rio)
            obj = form_saude.save()

            # Se veio foto no form, sincroniza com Participante
            foto = form_saude.cleaned_data.get('foto')
            if foto:
                participante.foto = foto
                participante.save(update_fields=['foto'])

            # Marca opt-in de marketing se houve consentimento
            if consent_ok:
                prefs, _ = PreferenciasComunicacao.objects.get_or_create(participante=participante)
                if not prefs.whatsapp_marketing_opt_in:
                    ip = request.META.get('REMOTE_ADDR')
                    ua = request.META.get('HTTP_USER_AGENT')
                    prova = f"IP={ip} | UA={ua} | ts={timezone.now().isoformat()}"
                    try:
                        prefs.marcar_optin_marketing(fonte='form', prova=prova, versao='v1')
                    except AttributeError:
                        prefs.whatsapp_marketing_opt_in = True
                        prefs.whatsapp_optin_data = timezone.now()
                        prefs.whatsapp_optin_fonte = 'form'
                        prefs.whatsapp_optin_prova = prova
                        prefs.politica_versao = 'v1'
                        prefs.save()

            # Marca inscriÃƒÂ§ÃƒÂ£o como enviada (disparos automÃƒÂ¡ticos ficam no save do modelo)
            if not inscricao.inscricao_enviada:
                inscricao.inscricao_enviada = True
                inscricao.save(update_fields=['inscricao_enviada'])

            messages.success(request, "Dados de saÃƒÂºde enviados com sucesso.")
            return redirect('inscricoes:ver_inscricao', pk=inscricao.id)
        else:
            # Debug opcional
            print("Erros no DadosSaudeForm:", form_saude.errors)
    else:
        # GET: carrega com dados jÃƒÂ¡ salvos
        form_saude = SaudeForm(instance=base_inscricao)

    return render(request, 'inscricoes/formulario_saude.html', {
        'form': form_saude,
        'inscricao': inscricao,
        'evento': evento,
        'politica': politica,
    })



def preencher_dados_contato(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    participante = inscricao.participante  # Associe ao participante da inscriÃƒÂ§ÃƒÂ£o

    if request.method == 'POST':
        form = ContatoForm(request.POST)
        if form.is_valid():
            contato = form.save(commit=False)
            contato.participante = participante  # Associa ao participante
            contato.save()

            # Redireciona para a etapa final (dados de saÃƒÂºde ou pÃƒÂ¡gina de sucesso)
            return redirect('preencher_dados_saude', inscricao_id=inscricao.id)
    else:
        form = ContatoForm()

    return render(request, 'dados_contato.html', {'form': form, 'inscricao': inscricao})

def form_inscricao(request):
    if request.method == "POST":
        cpf = request.POST.get("cpf")
        participante, criado = Participante.objects.get_or_create(cpf=cpf)
        participante.nome = request.POST.get("nome")
        participante.email = request.POST.get("email")
        participante.telefone = request.POST.get("telefone")
        participante.finalizado = True
        participante.save()
        return redirect('inscricoes:inscricao_finalizada', pk=participante.inscricao.id)

    return render(request, "inscricao.html")

def inscricao_finalizada(request, pk):
    inscricao = get_object_or_404(Inscricao, id=pk)
    return render(request, 'inscricoes/inscricao_finalizada.html', {'inscricao': inscricao})


from django.shortcuts import render, get_object_or_404
from .models import EventoAcampamento, Inscricao

def _valid_relation_names(model):
    """Conjunto com nomes de FKs/OneToOne (concretos) do model."""
    return {
        f.name for f in model._meta.get_fields()
        if getattr(f, 'is_relation', False) and getattr(f, 'concrete', False)
    }

def safe_select_related(qs, *names):
    """Aplica select_related apenas nos nomes válidos para o Model do queryset."""
    if not names:
        return qs
    valid = _valid_relation_names(qs.model)
    use = [n for n in names if n in valid]
    return qs.select_related(*use) if use else qs

def _pair_of(insc):
    """
    Descobre a inscrição 'par' conforme campos existentes no seu modelo.
    (ordem de preferência abaixo)
    """
    for attr in ("inscricao_pareada", "pareada_por", "conjuge"):
        if hasattr(insc, attr):
            par = getattr(insc, attr)
            if par:
                return par
    return None

def _city_qs_clean(values_qs):
    return sorted({c for c in values_qs if c})

def _base_rel_for_evento(insc):
    attr_by_tipo = {
        'senior':  'inscricaosenior',
        'juvenil': 'inscricaojuvenil',
        'mirim':   'inscricaomirim',
        'servos':  'inscricaoservos',
        'casais':  'inscricaocasais',
        'evento':  'inscricaoevento',
        'retiro':  'inscricaoretiro',
    }
    tipo = (getattr(getattr(insc, 'evento', None), 'tipo', '') or '').lower()
    preferida = attr_by_tipo.get(tipo)

    ordem = [preferida] if preferida else []
    ordem += [
        'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
        'inscricaocasais', 'inscricaoevento', 'inscricaoretiro'
    ]
    seen = set()
    for name in [n for n in ordem if n and n not in seen]:
        seen.add(name)
        if hasattr(insc, name):
            rel = getattr(insc, name)
            if rel:
                return rel
    return None


# --- VIEW --------------------------------------------------------------------

@login_required
def relatorio_crachas(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    cidade_selecionada = (request.GET.get('cidade') or '').strip()

    # Aplique select_related só nos campos que existem no seu Inscricao
    qs_base = safe_select_related(
        Inscricao.objects.filter(evento=evento, inscricao_concluida=True),
        # básicos
        'participante', 'paroquia', 'evento',
        # possíveis 'par' no SEU modelo (conforme traceback)
        'inscricao_pareada', 'pareada_por', 'conjuge',
        # bases por tipo
        'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim',
        'inscricaoservos', 'inscricaocasais', 'inscricaoevento', 'inscricaoretiro',
        # alocações
        'alocacao_ministerio', 'alocacao_ministerio__ministerio',
        'alocacao_grupo', 'alocacao_grupo__grupo',
    )

    # cidades do participante (limpas)
    cidades = _city_qs_clean(
        qs_base.values_list('participante__cidade', flat=True).distinct()
    )

    qs = qs_base
    if cidade_selecionada:
        qs = qs.filter(participante__cidade__iexact=cidade_selecionada)

    qs = qs.order_by('participante__nome')

    # deduplicação por casal
    ja_incluidos = set()
    inscricoes = []
    for insc in qs:
        if insc.id in ja_incluidos:
            continue

        par = _pair_of(insc)
        if par:
            menor, maior = (insc, par) if insc.id <= par.id else (par, insc)
            if insc != menor:
                # este é o segundo do par, pula (o menor entrará)
                continue
            ja_incluidos.add(maior.id)

        base = _base_rel_for_evento(insc)
        nasc = getattr(base, 'data_nascimento', None) if base else None
        if not nasc and hasattr(insc.participante, 'data_nascimento'):
            nasc = insc.participante.data_nascimento
        insc.nasc = nasc  # opcional: {{ inscricao.nasc|date:"d/m/Y" }}

        inscricoes.append(insc)

    cracha_template = CrachaTemplate.objects.first() if CrachaTemplate else None

    return render(request, 'inscricoes/relatorio_crachas.html', {
        'evento': evento,
        'inscricoes': inscricoes,
        'cidades': cidades,
        'cidade_selecionada': cidade_selecionada,
        'cracha_template': cracha_template,
    })

@login_required
def relatorio_fichas_sorteio(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    cidade = (request.GET.get("cidade") or "").strip()

    # ✅ TODAS as inscrições do evento (sem filtrar por concluída/selecionada/paga)
    inscricoes = (Inscricao.objects
                  .filter(evento=evento)
                  .select_related('participante', 'paroquia',
                                  'inscricaoservos', 'inscricaocasais',
                                  'inscricao_pareada', 'pareada_por', 'conjuge')
                  .order_by('participante__nome'))

    # Filtro opcional por cidade (aqui mantido por cidade da paróquia; mude se quiser usar a cidade do participante)
    if cidade:
        inscricoes = inscricoes.filter(paroquia__cidade__iexact=cidade)

    cidades = (Inscricao.objects.filter(evento=evento)
               .values_list('paroquia__cidade', flat=True)
               .distinct()
               .order_by('paroquia__cidade'))

    return render(request, 'inscricoes/relatorio_fichas_sorteio.html', {
        'evento': evento,
        'inscricoes': inscricoes,
        'cidades': cidades,
        'cidade_selecionada': cidade,
    })

@login_required
def relatorio_inscritos(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    cidade_filtro       = request.GET.get('cidade', '')
    status_filtro       = request.GET.get('status', '')
    selecionado_filtro  = request.GET.get('selecionado', '')

    # Filtros especiais (apenas para CASAIS)
    casais_mode = (getattr(evento, 'tipo', '') or '').lower() == 'casais'
    casado_igreja_filtro = request.GET.get('casado_igreja', '') if casais_mode else ''
    tempo_casados_filtro = request.GET.get('tempo_casados', '') if casais_mode else ''

    # 1) InscriÃƒÂ§ÃƒÂµes do evento
    inscricoes = Inscricao.objects.filter(evento=evento)

    # 2) Filtros bÃƒÂ¡sicos
    if cidade_filtro:
        inscricoes = inscricoes.filter(participante__cidade=cidade_filtro)

    if status_filtro == 'concluida':
        inscricoes = inscricoes.filter(inscricao_concluida=True)
    elif status_filtro == 'pendente':
        inscricoes = inscricoes.filter(inscricao_concluida=False)

    if selecionado_filtro == 'sim':
        inscricoes = inscricoes.filter(foi_selecionado=True)
    elif selecionado_filtro == 'nao':
        inscricoes = inscricoes.filter(foi_selecionado=False)

    # 2.1) Filtros de CASAIS (somente se tipo=casais)
    if casais_mode:
        if casado_igreja_filtro == 'sim':
            inscricoes = inscricoes.filter(inscricaocasais__casado_na_igreja=True)
        elif casado_igreja_filtro == 'nao':
            inscricoes = inscricoes.filter(inscricaocasais__casado_na_igreja=False)
        if tempo_casados_filtro:
            inscricoes = inscricoes.filter(
                inscricaocasais__tempo_casado_uniao__icontains=tempo_casados_filtro
            )

    # 3) Participantes e cidades (para o filtro de cidades)
    participantes = Participante.objects.filter(inscricao__in=inscricoes).distinct()
    cidades = participantes.values_list('cidade', flat=True).distinct().order_by('cidade')

    # 4) Carrega possÃƒÂ­veis OneToOne para evitar N+1
    inscricoes_qs = (
        inscricoes
        .select_related(
            'participante',
            'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
            'inscricaocasais', 'inscricaoevento', 'inscricaoretiro'
        )
    )

    # 4.1) Mapa por tipo
    attr_by_tipo = {
        'senior':  'inscricaosenior',
        'juvenil': 'inscricaojuvenil',
        'mirim':   'inscricaomirim',
        'servos':  'inscricaoservos',
        'casais':  'inscricaocasais',
        'evento':  'inscricaoevento',
        'retiro':  'inscricaoretiro',
    }

    def get_base_rel(i: Inscricao):
        """
        Retorna o objeto BaseInscricao do tipo correto conforme i.evento.tipo.
        Se nÃƒÂ£o existir, tenta fallback nas outras relaÃƒÂ§ÃƒÂµes.
        """
        nomes = []
        tipo = (getattr(i.evento, 'tipo', '') or '').lower()
        preferida = attr_by_tipo.get(tipo)
        if preferida:
            nomes.append(preferida)
        nomes += [
            'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
            'inscricaocasais', 'inscricaoevento', 'inscricaoretiro'
        ]
        seen = set()
        for name in [n for n in nomes if n and n not in seen]:
            seen.add(name)
            try:
                return getattr(i, name)
            except ObjectDoesNotExist:
                continue
        return None

    # 5) Monta "linhas" prontas para o template, jÃƒÂ¡ com dupla (A Ã¢â‚¬â€ B) quando couber
    rows = []
    seen_ids = set()  # para evitar duplicar a "segunda" inscriÃƒÂ§ÃƒÂ£o do casal/servo-vinculado

    for i in inscricoes_qs:
        # Evita duplicidade (mesma regra usada em outras telas)
        try:
            # atributos comuns usados no resto do projeto
            if (getattr(i, 'par', None) and i.par.id < i.id) \
               or (getattr(i, 'par_inscrito', None) and i.par_inscrito.id < i.id) \
               or (getattr(i, 'inscricao_casal', None) and i.inscricao_casal.id < i.id) \
               or (getattr(i, 'casal_vinculado', None) and i.casal_vinculado.id < i.id):
                continue
        except Exception:
            pass

        rel = get_base_rel(i)
        camisa = (getattr(rel, 'tamanho_camisa', '') or '').upper()
        nasc   = getattr(rel, 'data_nascimento', None) or getattr(i.participante, 'data_nascimento', None)

        # Nome "A Ã¢â‚¬â€ B" (para casais ou servos vinculados)
        nome_a = i.participante.nome
        nome_b = None
        # tenta descobrir o parceiro
        partner = None
        if getattr(i, 'par', None):
            partner = i.par
        elif getattr(i, 'par_inscrito', None):
            partner = i.par_inscrito
        elif getattr(i, 'inscricao_casal', None):
            partner = i.inscricao_casal
        elif getattr(i, 'casal_vinculado', None):
            partner = i.casal_vinculado

        if partner and getattr(partner, 'participante', None):
            nome_b = partner.participante.nome

        nome_display = f"{nome_a} Ã¢â‚¬â€ {nome_b}" if nome_b else nome_a

        # Campos exclusivos de CASAIS
        tempo_casado = getattr(rel, 'tempo_casado_uniao', '') if casais_mode else ''
        casado_igreja = getattr(rel, 'casado_na_igreja', None) if casais_mode else None

        rows.append({
            "id": i.id,
            "nome": nome_display,
            "cidade": i.participante.cidade,
            "estado": i.participante.estado,
            "telefone": i.participante.telefone,
            "email": i.participante.email,
            "camisa": camisa or "-",
            "nasc": nasc,
            "status_label": "ConcluÃƒÂ­da" if i.inscricao_concluida else "Pendente",
            "selecionado": bool(i.foi_selecionado),
            "tempo_casado": tempo_casado or "",
            "casado_na_igreja": casado_igreja,  # True/False/None
        })

    # 6) Totais por tamanho de camisa (usa choices do BaseInscricao)
    tamanhos = [t for (t, _) in BaseInscricao.TAMANHO_CAMISA_CHOICES]
    quantidades_camisas = { t.lower(): 0 for t in tamanhos }
    for i in inscricoes_qs:
        rel = get_base_rel(i)
        if rel:
            size = (getattr(rel, 'tamanho_camisa', '') or '').upper()
            key = size.lower()
            if key in quantidades_camisas:
                quantidades_camisas[key] += 1

    return render(request, 'inscricoes/relatorio_inscritos.html', {
        'evento': evento,
        'cidades': cidades,
        'rows': rows,
        'cidade_filtro': cidade_filtro,
        'status_filtro': status_filtro,
        'selecionado_filtro': selecionado_filtro,
        'casais_mode': casais_mode,
        'casado_igreja_filtro': casado_igreja_filtro,
        'tempo_casados_filtro': tempo_casados_filtro,
        'quantidades_camisas': quantidades_camisas,
        'now': timezone.now(),
    })



# RelatÃƒÂ³rio Financeiro
def relatorio_financeiro(request, evento_id):
    evento = get_object_or_404(evento, id=evento_id)
    participantes = Participante.objects.filter(inscricao__evento=evento)
    # Em versÃƒÂ£o futura, pode incluir valores pagos, totais, etc.
    return render(request, 'relatorios/relatorio_financeiro.html', {
        'evento': evento,
        'participantes': participantes
    })

def pagina_video_evento(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # o vÃƒÂ­deo estÃƒÂ¡ em evento.video.arquivo, se existir
    video = getattr(evento, 'video', None)
    return render(request, 'inscricoes/video_evento.html', {
        'evento': evento,
        'video': video,
    })

def alterar_politica(request):
    politica = PoliticaPrivacidade.objects.first()  # Pega a primeira (e ÃƒÂºnica) polÃƒÂ­tica
    if not politica:
        politica = PoliticaPrivacidade.objects.create() # Cria se nÃƒÂ£o existir

    if request.method == 'POST':
        form = PoliticaPrivacidadeForm(request.POST, request.FILES, instance=politica)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_dashboard')  # Redireciona para o dashboard apÃƒÂ³s salvar
    else:
        form = PoliticaPrivacidadeForm(instance=politica)

    return render(request, 'inscricoes/alterar_politica.html', {'form': form})

def _q2(v):  # arredonda para 2 casas
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _calc_taxa_liquido(pagamento, mp_cfg):
    """Calcula (taxa, lÃƒÂ­quido) a partir do mÃƒÂ©todo e das taxas da config.
       Se jÃƒÂ¡ houver net_received/fee_mp no banco, usa-os."""
    if pagamento.net_received and pagamento.fee_mp is not None:
        return _q2(pagamento.fee_mp), _q2(pagamento.net_received)

    valor = _q2(pagamento.valor)
    metodo = (pagamento.metodo or "").lower()
    pct = fixo = Decimal("0.00")

    if mp_cfg:
        if metodo == "pix":
            pct, fixo = Decimal(mp_cfg.taxa_pix_percent or 0), Decimal(mp_cfg.taxa_pix_fixa or 0)
        elif metodo == "credito":
            pct, fixo = Decimal(mp_cfg.taxa_credito_percent or 0), Decimal(mp_cfg.taxa_credito_fixa or 0)
        elif metodo == "debito":
            pct, fixo = Decimal(mp_cfg.taxa_debito_percent or 0), Decimal(mp_cfg.taxa_debito_fixa or 0)
        # dinheiro: normalmente sem taxa

    taxa = _q2(valor * (pct/Decimal("100")) + fixo)
    liquido = _q2(valor - taxa)
    if liquido < 0:
        liquido = Decimal("0.00")
    return taxa, liquido

def _to_decimal_or_none(s: str | None) -> Decimal | None:
    if not s:
        return None
    try:
        return Decimal(s.replace(",", "."))
    except Exception:
        return None

def relatorio_financeiro(request, evento_id):
    """
    RelatÃƒÂ³rio financeiro do evento com visÃƒÂ£o Bruto/LÃƒÂ­quido/Taxas e Repasse.
    - Repasse via querystring (?repasse=XX.YY) sÃƒÂ³ ÃƒÂ© aceito para admin_geral.
    - Repasse padrÃƒÂ£o: evento.repasse_percentual_override -> paroquia.repasse_percentual -> 0
    """
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    # --- 0) Flags de permissÃƒÂ£o ---
    is_admin_geral = bool(
        getattr(request.user, "is_authenticated", False)
        and getattr(request.user, "tipo_usuario", "") == "admin_geral"
    )
    is_admin_paroquia = bool(
        getattr(request.user, "is_authenticated", False)
        and getattr(request.user, "tipo_usuario", "") == "admin_paroquia"
        and getattr(request.user, "paroquia_id", None) == evento.paroquia_id
    )

    # --- 1) Percentual de repasse (prioridade + trava de permissÃƒÂ£o) ---
    repasse_qs = _to_decimal_or_none(request.GET.get("repasse"))
    if is_admin_geral and repasse_qs is not None:
        repasse_percentual = repasse_qs
    elif getattr(evento, "repasse_percentual_override", None) is not None:
        repasse_percentual = Decimal(evento.repasse_percentual_override or 0)
    else:
        repasse_percentual = Decimal(getattr(evento.paroquia, "repasse_percentual", 0) or 0)
    repasse_percentual = _q2(repasse_percentual)

    # --- 2) Pagamentos confirmados ---
    pagos = (
        Pagamento.objects
        .select_related("inscricao__evento__paroquia", "inscricao__paroquia")
        .filter(
            inscricao__evento=evento,
            status=Pagamento.StatusPagamento.CONFIRMADO
        )
        .order_by("inscricao_id")
    )

    # --- 3) DeduplicaÃƒÂ§ÃƒÂ£o (casais/pagamento): conta 1 por par ---
    dedup = []
    vistos = set()
    tipo_lower = (evento.tipo or "").lower()
    dedup_por_par = tipo_lower in {"casais", "pagamento"}  # ajuste conforme sua regra

    for p in pagos:
        ins = p.inscricao
        if dedup_por_par:
            par_id = getattr(ins, "inscricao_pareada_id", None) or getattr(ins, "pareada_por_id", None)
            if par_id:
                raiz = min(ins.id, par_id)
                if raiz in vistos:
                    continue
                vistos.add(raiz)
        dedup.append(p)

    # --- 4) KPIs por mÃƒÂ©todo (bruto / lÃƒÂ­quido) + totais ---
    mp_cfg = getattr(evento.paroquia, "mp_config", None)
    totals = {
        "pix":      {"bruto": Decimal("0.00"), "liq": Decimal("0.00")},
        "credito":  {"bruto": Decimal("0.00"), "liq": Decimal("0.00")},
        "debito":   {"bruto": Decimal("0.00"), "liq": Decimal("0.00")},
        "dinheiro": {"bruto": Decimal("0.00"), "liq": Decimal("0.00")},
    }

    for p in dedup:
        metodo = (p.metodo or "").lower()
        if metodo not in totals:
            metodo = "dinheiro"  # fallback
        bruto = _q2(p.valor)
        _taxa, liquido = _calc_taxa_liquido(p, mp_cfg)
        totals[metodo]["bruto"] += bruto
        totals[metodo]["liq"]   += liquido

    total_pix_bruto      = _q2(totals["pix"]["bruto"])
    total_credito_bruto  = _q2(totals["credito"]["bruto"])
    total_debito_bruto   = _q2(totals["debito"]["bruto"])
    total_dinheiro_bruto = _q2(totals["dinheiro"]["bruto"])

    total_pix_liq      = _q2(totals["pix"]["liq"])
    total_credito_liq  = _q2(totals["credito"]["liq"])
    total_debito_liq   = _q2(totals["debito"]["liq"])
    total_dinheiro_liq = _q2(totals["dinheiro"]["liq"])

    total_arrecadado_bruto = _q2(total_pix_bruto + total_credito_bruto + total_debito_bruto + total_dinheiro_bruto)
    total_arrecadado_liq   = _q2(total_pix_liq + total_credito_liq + total_debito_liq + total_dinheiro_liq)
    total_taxas            = _q2(total_arrecadado_bruto - total_arrecadado_liq)

    # --- 5) Total esperado (conta 1 por casal quando for casais/pagamento) ---
    inscricoes = Inscricao.objects.filter(evento=evento).only("id", "inscricao_pareada")
    if dedup_por_par:
        unidades = 0
        for i in inscricoes:
            par_id = getattr(i, "inscricao_pareada_id", None) or getattr(i, "pareada_por_id", None)
            if not par_id or i.id < par_id:  # sÃƒÂ³ um da dupla conta
                unidades += 1
    else:
        unidades = inscricoes.count()

    total_esperado = _q2(Decimal(evento.valor_inscricao or 0) * Decimal(unidades))
    total_pendente_bruto = _q2(max(Decimal("0.00"), total_esperado - total_arrecadado_bruto))
    total_pendente_liq   = _q2(max(Decimal("0.00"), total_esperado - total_arrecadado_liq))

    # --- 6) REPASSE Ã‚â€” previsto (sobre o LÃƒÂQUIDO) e consolidaÃƒÂ§ÃƒÂ£o de pendentes/pagos ---
    repasse_previsto_val = _q2(total_arrecadado_liq * (repasse_percentual / Decimal("100")))

    repasses_pendentes = Repasse.objects.filter(
        paroquia=evento.paroquia, evento=evento, status=Repasse.Status.PENDENTE
    ).order_by("-criado_em")
    repasses_pagos = Repasse.objects.filter(
        paroquia=evento.paroquia, evento=evento, status=Repasse.Status.PAGO
    ).order_by("-atualizado_em")

    pend_base = _q2(repasses_pendentes.aggregate(s=Sum("valor_base"))["s"] or Decimal("0.00"))
    pend_val  = _q2(repasses_pendentes.aggregate(s=Sum("valor_repasse"))["s"] or Decimal("0.00"))
    pago_base = _q2(repasses_pagos.aggregate(s=Sum("valor_base"))["s"] or Decimal("0.00"))
    pago_val  = _q2(repasses_pagos.aggregate(s=Sum("valor_repasse"))["s"] or Decimal("0.00"))

    # VisÃƒÂµes ÃƒÂºteis p/ a parÃƒÂ³quia
    liquido_pos_repasse_previsto = _q2(total_arrecadado_liq - repasse_previsto_val)
    liquido_pos_repasse_pendente = _q2(total_arrecadado_liq - pend_val)
    liquido_pos_repasse_pago     = _q2(total_arrecadado_liq - pago_val)

    context = {
        "evento": evento,

        # bruto (compatibilidade com template)
        "total_arrecadado": total_arrecadado_bruto,
        "total_esperado":   total_esperado,
        "total_pendente":   total_pendente_bruto,
        "total_pix":        total_pix_bruto,
        "total_credito":    total_credito_bruto,
        "total_debito":     total_debito_bruto,
        "total_dinheiro":   total_dinheiro_bruto,

        # tabela (deduplicada)
        "pagamentos_confirmados": dedup,

        # lÃƒÂ­quido e taxas
        "total_liquido":          total_arrecadado_liq,
        "total_taxas":            total_taxas,
        "total_pendente_liquido": total_pendente_liq,
        "total_pix_liquido":      total_pix_liq,
        "total_credito_liquido":  total_credito_liq,
        "total_debito_liquido":   total_debito_liq,
        "total_dinheiro_liquido": total_dinheiro_liq,

        # repasse
        "repasse_percentual_usado": repasse_percentual,
        "repasse_previsto":         repasse_previsto_val,

        "repasses_pendentes": repasses_pendentes,
        "repasses_pagos":     repasses_pagos,

        "repasses_pendentes_base_total": pend_base,
        "repasses_pendentes_valor_total": pend_val,
        "repasses_pagos_base_total":      pago_base,
        "repasses_pagos_valor_total":     pago_val,

        "liquido_pos_repasse_previsto":  liquido_pos_repasse_previsto,
        "liquido_pos_repasse_pendente":  liquido_pos_repasse_pendente,
        "liquido_pos_repasse_pago":      liquido_pos_repasse_pago,

        # extras p/ template (habilita botÃƒÂ£o Gerar/Ver QR para admin da parÃƒÂ³quia)
        "is_admin_geral": is_admin_geral,
        "is_admin_paroquia": is_admin_paroquia,
        "current_year": timezone.localdate().year,
    }
    return render(request, "inscricoes/relatorio_financeiro.html", context)

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def ver_logs_bruto(request):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'usuarios.log')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            linhas = f.readlines()[-200:]
    else:
        linhas = ["Arquivo de log nÃƒÂ£o encontrado."]
    return render(request, 'logs/ver_logs.html', {'linhas': linhas})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def ver_logs_lista(request):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'usuarios.log')
    eventos = []

    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                linhas = f.readlines()[-200:]
                for linha in linhas:
                    if 'LOGIN:' in linha:
                        partes = linha.split('|')
                        horario = partes[0].strip()
                        usuario = partes[-1].split('LOGIN: ')[1].split('|')[0].strip()
                        ip = partes[-1].split('IP: ')[1].strip()
                        eventos.append({'tipo': 'login', 'usuario': usuario, 'ip': ip, 'hora': horario})
                    elif 'LOGOUT:' in linha:
                        partes = linha.split('|')
                        horario = partes[0].strip()
                        usuario = partes[-1].split('LOGOUT: ')[1].split('|')[0].strip()
                        ip = partes[-1].split('IP: ')[1].strip()
                        eventos.append({'tipo': 'logout', 'usuario': usuario, 'ip': ip, 'hora': horario})
                    elif 'acessou' in linha:
                        partes = linha.split('|')
                        horario = partes[0].strip()
                        if 'acessou' in partes[-1]:
                            user_info = partes[-1].strip().split()
                            usuario = user_info[1]
                            caminho = partes[-1].split('acessou')[1].strip()
                            eventos.append({'tipo': 'acesso', 'usuario': usuario, 'caminho': caminho, 'hora': horario})
        except Exception as e:
            eventos.append({'tipo': 'erro', 'mensagem': f'Erro ao ler o arquivo de log: {str(e)}'})
    else:
        eventos.append({'tipo': 'erro', 'mensagem': 'Arquivo de log nÃƒÂ£o encontrado.'})

    return render(request, 'logs/ver_logs_lista.html', {'eventos': eventos})

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def download_logs(request):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'usuarios.log')
    if os.path.exists(log_path):
        return FileResponse(open(log_path, 'rb'), as_attachment=True, filename='usuarios.log')
    else:
        return HttpResponse("Arquivo de log nÃƒÂ£o encontrado.", status=404)
    
@require_GET
def pagina_video_evento(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # Se houver relaÃƒÂ§ÃƒÂ£o OneToOne chamada "video"
    video = getattr(evento, "video", None)
    return render(request, "inscricoes/video_evento_publico.html", {
        "evento": evento,
        "video": video,
    })

User = get_user_model()

def alterar_credenciais(request, pk):
    user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = AlterarCredenciaisForm(request.POST, instance=user)
        if form.is_valid():
            user.username = form.cleaned_data['username']
            user.password = make_password(form.cleaned_data['password'])
            user.save()
            messages.success(request, 'Credenciais atualizadas com sucesso!')
            return redirect('login')
    else:
        form = AlterarCredenciaisForm(instance=user)

    return render(request, 'inscricoes/alterar_credenciais.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_admin_geral())
def cadastrar_pastoral_movimento(request):
    if request.method == 'POST':
        form = PastoralMovimentoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '? Pastoral/Movimento cadastrado com sucesso!')
            return redirect('inscricoes:listar_pastorais_movimentos')
    else:
        form = PastoralMovimentoForm()
    return render(request, 'pastorais/cadastrar.html', {'form': form})

@login_required
@user_passes_test(lambda u: u.is_admin_geral())
def listar_pastorais_movimentos(request):
    pastorais = PastoralMovimento.objects.all()
    return render(request, 'pastorais/listar.html', {'pastorais': pastorais})

from django.shortcuts import render, get_object_or_404
from .models import EventoAcampamento, Participante, Inscricao

def verificar_selecao(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    status = None
    participante = None

    cpf = request.GET.get('cpf', '').strip()
    if cpf:
        try:
            participante = Participante.objects.get(cpf=cpf)
            inscricao = Inscricao.objects.get(
                evento=evento,
                participante=participante
            )
            # True ou False
            status = inscricao.foi_selecionado
        except Participante.DoesNotExist:
            status = 'nao_encontrado'
        except Inscricao.DoesNotExist:
            status = 'sem_inscricao'

    return render(request, 'inscricoes/verificar_selecao.html', {
        'evento': evento,
        'status': status,
        'participante': participante,
        'cpf': cpf,
    })

def is_admin_paroquia(user):
    return hasattr(user, 'is_admin_paroquia') and user.is_admin_paroquia()

def is_admin_paroquia(user):
    return user.is_authenticated and hasattr(user, 'is_admin_paroquia') and user.is_admin_paroquia()

def _is_admin_paroquia(user):
    return user.is_authenticated and hasattr(user, "is_admin_paroquia") and user.is_admin_paroquia()

@login_required
@user_passes_test(_is_admin_paroquia)
def mp_config(request):
    paroquia = getattr(request.user, "paroquia", None)
    if not paroquia:
        messages.error(request, "Seu usuÃƒÂ¡rio nÃƒÂ£o estÃƒÂ¡ vinculado a uma parÃƒÂ³quia.")
        return redirect("inscricoes:admin_paroquia_painel")

    config, _ = MercadoPagoConfig.objects.get_or_create(paroquia=paroquia)

    if request.method == "POST":
        form = MercadoPagoConfigForm(request.POST, instance=config)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.paroquia = paroquia  # garante vÃƒÂ­nculo correto
            obj.save()
            messages.success(request, "ConfiguraÃƒÂ§ÃƒÂ£o do Mercado Pago salva com sucesso!")
            return redirect("inscricoes:admin_paroquia_painel")
        else:
            messages.error(request, "Revise os campos destacados e tente novamente.")
    else:
        form = MercadoPagoConfigForm(instance=config)

    politica = PoliticaPrivacidade.objects.first()

    return render(
        request,
        "inscricoes/mp_config.html",
        {
            "form": form,
            "paroquia": paroquia,
            "politica": politica,  # usado para exibir o aviso de suporte
        },
    )

# ===== Helpers ===============================================================

def _mp_client_by_paroquia(paroquia):
    cfg = getattr(paroquia, "mp_config", None)
    if not cfg or not cfg.access_token:
        raise ValueError("Mercado Pago nÃƒÂ£o configurado para esta parÃƒÂ³quia.")
    return mercadopago.SDK(cfg.access_token.strip())

MP_APPROVED_STATUSES = {"approved", "paid", "authorized"}
MP_PENDING_STATUSES = {"pending", "in_process", "in_process_review", "in_progress", "in_review"}
MP_CANCELLED_STATUSES = {"cancelled", "rejected", "refunded", "charged_back", "cancelled_by_user"}

# --- Helpers de Webhook (formatos novos/antigos) -----------------------------
def _extract_mp_notification(request):
    """
    Retorna (kind, payment_id) onde kind ∈ {'payment','merchant_order','unknown'}.
    Aceita JSON e x-www-form-urlencoded (v1/v2).
    """
    kind = "unknown"
    payment_id = None

    # 1) Tenta JSON
    try:
        payload = json.loads(request.body or b"{}")
        data = payload.get("data") or {}
        # v2: {"type":"payment","data":{"id":"123"}}
        if payload.get("type") in ("payment", "merchant_order"):
            kind = payload["type"]
            payment_id = str(data.get("id") or payload.get("id") or "").strip() or None
            if payment_id:
                return kind, payment_id
        # v1: {"topic": "payment", "id": "123"}
        if payload.get("topic") in ("payment","merchant_order"):
            kind = "payment" if payload["topic"] == "payment" else "merchant_order"
            payment_id = str(payload.get("id") or "").strip() or None
            if payment_id:
                return kind, payment_id
    except Exception:
        pass

    # 2) Tenta form/urlencoded
    try:
        body_qs = QueryDict((request.body or b"").decode("utf-8"), encoding="utf-8")
        topic = body_qs.get("type") or body_qs.get("topic") or ""
        if topic in ("payment","merchant_order"):
            kind = "payment" if topic == "payment" else "merchant_order"
            payment_id = body_qs.get("id") or (body_qs.get("data.id") or "").strip() or None
            if payment_id:
                return kind, str(payment_id)
    except Exception:
        pass

    # 3) Querystring (?id=...&type=payment)
    t = (request.GET.get("type") or request.GET.get("topic") or "").strip()
    if t in ("payment","merchant_order"):
        kind = "payment" if t == "payment" else "merchant_order"
        payment_id = (request.GET.get("id") or "").strip() or None

    return kind, payment_id


def _get_inscricao_by_payment_id_local(payment_id: str):
    """
    Tenta achar a inscrição pelo transacao_id já salvo (PIX e alguns cartões).
    """
    try:
        pg = Pagamento.objects.select_related("inscricao","inscricao__paroquia").get(transacao_id=str(payment_id))
        return pg.inscricao
    except Pagamento.DoesNotExist:
        return None


def _fetch_payment_with_any_token(payment_id: str):
    """
    Percorre todas as credenciais (paróquias) até achar o pagamento.
    Retorna o dict 'response' do MP ou None.
    """
    configs = (MercadoPagoConfig.objects
               .exclude(access_token__isnull=True)
               .exclude(access_token__exact="")
               .only("id","access_token"))
    for cfg in configs:
        try:
            sdk = mercadopago.SDK(cfg.access_token.strip())
            resp = sdk.payment().get(payment_id) or {}
            data = resp.get("response")
            if isinstance(data, dict) and str(data.get("id") or "") == str(payment_id):
                return data
        except Exception:
            continue
    return None

def _public_https(url_name: str, *args, _request=None, **kwargs) -> str:
    base = (getattr(settings, "SITE_URL", "") or getattr(settings, "SITE_DOMAIN", "") or "").rstrip("/")
    if base.startswith("https://"):
        return urljoin(base + "/", reverse(url_name, args=args, kwargs=kwargs).lstrip("/"))
    # fallback (dev)
    if _request is not None:
        return _request.build_absolute_uri(reverse(url_name, args=args, kwargs=kwargs))
    return reverse(url_name, args=args, kwargs=kwargs)


def _parse_mp_datetime(dt_str):
    if not dt_str:
        return None
    dt = parse_datetime(dt_str)
    if not dt:
        return None
    # if naive, assume UTC (MP usually envia com Z)
    if dj_timezone.is_naive(dt):
        dt = dj_timezone.make_aware(dt, dj_timezone.utc)
    return dt

def _sincronizar_pagamento(mp_client, inscricao, payment_id):
    """
    Busca o pagamento no MP, garante que o external_reference bate com a inscriÃ§Ã£o
    e sincroniza o registro OneToOne Pagamento dessa inscriÃ§Ã£o.
    """
    payment = mp_client.payment().get(payment_id)["response"]

    # SeguranÃ§a: confere vÃ­nculo
    if str(payment.get("external_reference")) != str(inscricao.id):
        raise ValueError("Pagamento nÃ£o corresponde Ã  inscriÃ§Ã£o.")

    # Atualiza sempre o mesmo registro (OneToOne)
    pagamento, _ = Pagamento.objects.get_or_create(inscricao=inscricao)
    pagamento.transacao_id = str(payment.get("id") or "")
    pagamento.metodo = payment.get("payment_method_id", Pagamento.MetodoPagamento.PIX)
    pagamento.valor = payment.get("transaction_amount", 0) or 0

    status = payment.get("status")
    if status == "approved":
        pagamento.status = Pagamento.StatusPagamento.CONFIRMADO
        inscricao.pagamento_confirmado = True
        inscricao.inscricao_concluida = True
        inscricao.save(update_fields=["pagamento_confirmado", "inscricao_concluida"])
    elif status in ("pending", "in_process"):
        pagamento.status = Pagamento.StatusPagamento.PENDENTE
    else:
        pagamento.status = Pagamento.StatusPagamento.CANCELADO

    pagamento.data_pagamento = parse_datetime(payment.get("date_approved")) if payment.get("date_approved") else None
    pagamento.save()
    return status

def _sync_pagamento_from_mp_dict(inscricao: Inscricao, payment: dict) -> str:
    """
    Sincroniza inscrição/pagamento a partir do dict do MP.
    Retorna 'approved'/'pending'/... conforme MP.
    """
    ext_ref = str(payment.get("external_reference") or "").strip()
    meta_inscricao = str(((payment.get("metadata") or {}).get("inscricao_id")) or "").strip()

    if ext_ref and str(ext_ref) != str(inscricao.id):
        if meta_inscricao and str(meta_inscricao) != str(inscricao.id):
            raise ValueError("Pagamento não corresponde à inscrição.")

    pagamento, _ = Pagamento.objects.get_or_create(inscricao=inscricao)
    pagamento.transacao_id = str(payment.get("id") or pagamento.transacao_id or "")
    pagamento.metodo = (payment.get("payment_method_id") or pagamento.metodo or Pagamento.MetodoPagamento.PIX)
    pagamento.valor = payment.get("transaction_amount", pagamento.valor or 0) or 0

    status = (payment.get("status") or "").lower().strip()

    if status in MP_APPROVED_STATUSES:
        pagamento.status = Pagamento.StatusPagamento.CONFIRMADO
        inscricao.pagamento_confirmado = True
        inscricao.inscricao_concluida = True
        inscricao.save(update_fields=["pagamento_confirmado","inscricao_concluida"])
        try:
            d = payment.get("date_approved") or payment.get("money_release_date")
            pagamento.data_pagamento = parse_datetime(d) if d else pagamento.data_pagamento
        except Exception:
            pass
    elif status in MP_PENDING_STATUSES:
        pagamento.status = Pagamento.StatusPagamento.PENDENTE
    elif status in MP_CANCELLED_STATUSES:
        pagamento.status = Pagamento.StatusPagamento.CANCELADO
    else:
        pagamento.status = Pagamento.StatusPagamento.PENDENTE

    pagamento.save()
    return status


# ===== Iniciar pagamento =====================================================

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.conf import settings
from django.utils.timezone import now
from django.contrib import messages
from urllib.parse import urljoin
import mercadopago, logging
from .models import Inscricao, Pagamento

def iniciar_pagamento(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Regras de negÃ³cio
    if not inscricao.foi_selecionado:
        messages.error(request, "InscriÃ§Ã£o ainda nÃ£o selecionada. Aguarde a seleÃ§Ã£o para pagar.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

    if inscricao.pagamento_confirmado:
        messages.info(request, "Pagamento jÃ¡ confirmado para esta inscriÃ§Ã£o.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

    # Config da ParÃ³quia
    try:
        config = inscricao.paroquia.mp_config
    except MercadoPagoConfig.DoesNotExist:
        messages.error(request, "Pagamento nÃ£o configurado para esta parÃ³quia.")
        return redirect("inscricoes:pagina_de_contato")

    access_token = (config.access_token or "").strip()
    if not access_token:
        messages.error(request, "Pagamento nÃ£o configurado. Entre em contato com a organizaÃ§Ã£o.")
        return redirect("inscricoes:pagina_de_contato")

    sdk = mercadopago.SDK(access_token)

    # URLs baseadas no request (local)â€¦
    sucesso_url = request.build_absolute_uri(reverse("inscricoes:mp_success", args=[inscricao.id]))
    falha_url   = request.build_absolute_uri(reverse("inscricoes:mp_failure", args=[inscricao.id]))
    pend_url    = request.build_absolute_uri(reverse("inscricoes:mp_pending", args=[inscricao.id]))
    webhook_url = request.build_absolute_uri(reverse("inscricoes:mp_webhook"))

    # â€¦mas se vocÃª tiver um domÃ­nio pÃºblico HTTPS em settings.SITE_DOMAIN, usa ele.
    site_domain = (getattr(settings, "SITE_DOMAIN", "") or "").rstrip("/")
    if site_domain.startswith("https://"):
        sucesso_url = urljoin(site_domain, reverse("inscricoes:mp_success", args=[inscricao.id]))
        falha_url   = urljoin(site_domain, reverse("inscricoes:mp_failure", args=[inscricao.id]))
        pend_url    = urljoin(site_domain, reverse("inscricoes:mp_pending", args=[inscricao.id]))
        webhook_url = _public_https("inscricoes:mp_webhook", _request=request)

    pref_data = {
        "items": [{
            "title": f"InscriÃ§Ã£o â€“ {inscricao.evento.nome}"[:60],
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": float(inscricao.evento.valor_inscricao),
        }],
        "payer": {"email": inscricao.participante.email},
        "external_reference": str(inscricao.id),
        "back_urls": {"success": sucesso_url, "failure": falha_url, "pending": pend_url},
        "notification_url": webhook_url,
        # "payment_methods": {"installments": 1},  # habilite se quiser travar parcelas
        # "binary_mode": True,                     # opcional (aprova ou rejeita; sem "in_process")
        "metadata": {
            "inscricao_id": inscricao.id,
            "paroquia_id": inscricao.paroquia_id,
            "evento_id": str(inscricao.evento_id),
            "criado_em": now().isoformat(),
        },
    }

    # SÃ³ adiciona auto_return se o success for HTTPS (exigÃªncia do MP)
    if sucesso_url.startswith("https://"):
        pref_data["auto_return"] = "approved"

    try:
        mp_pref = sdk.preference().create(pref_data)
        resp = mp_pref.get("response", {}) or {}
        logging.info("MP Preference response: %r", resp)

        # Erros comuns do MP (status 400 / message / error)
        if resp.get("status") == 400 or resp.get("error") or resp.get("message"):
            msg = resp.get("message") or "Falha ao criar preferÃªncia no Mercado Pago."
            if settings.DEBUG:
                return HttpResponse(f"<h3>Erro do MP</h3><pre>{resp}</pre>", content_type="text/html")
            messages.error(request, msg)
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        init_point = resp.get("init_point") or resp.get("sandbox_init_point")
        if not init_point:
            if settings.DEBUG:
                return HttpResponse("<h3>PreferÃªncia sem init_point</h3><pre>%s</pre>" % resp, content_type="text/html")
            messages.error(request, "PreferÃªncia criada sem link de checkout. Tente novamente.")
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        # Normaliza
        if not init_point.lower().startswith(("http://", "https://")):
            init_point = "https://" + init_point

        # Agora sim, cria/atualiza registro pendente para auditoria
        Pagamento.objects.update_or_create(
            inscricao=inscricao,
            defaults={
                "valor": inscricao.evento.valor_inscricao,
                "status": Pagamento.StatusPagamento.PENDENTE,
                "metodo": Pagamento.MetodoPagamento.PIX,  # o mÃ©todo real vem no webhook
            },
        )

        return redirect(init_point)

    except Exception as e:
        logging.exception("Erro ao criar preferÃªncia do Mercado Pago: %s", e)
        if settings.DEBUG:
            return HttpResponse(f"<h3>ExceÃ§Ã£o ao criar preferÃªncia</h3><pre>{e}</pre>", content_type="text/html")
        messages.error(request, "Erro ao iniciar pagamento. Tente novamente mais tarde.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

# ===== PÃƒÂ¡ginas de retorno (UX) ==============================================

@require_GET
def mp_success(request, inscricao_id):
    """
    PÃ¡gina de sucesso apÃ³s retorno do checkout do MP.
    - Valida/sincroniza o pagamento quando `payment_id` vier na querystring.
    - Renderiza 'pagamentos/sucesso.html' com:
        * inscricao
        * evento
        * politica (para exibir logo, imagens, inclusive `imagem_pagto`)
        * video_url (botÃ£o 'Assistir vÃ­deo de boas-vindas')
    """
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    payment_id = request.GET.get("payment_id")

    # Tenta sincronizar rapidamente se o MP mandou o payment_id no retorno
    if payment_id:
        try:
            mp = _mp_client_by_paroquia(inscricao.paroquia)
            _sincronizar_pagamento(mp, inscricao, payment_id)
        except Exception as e:
            # NÃ£o bloqueia a UX â€” o webhook ainda pode confirmar depois.
            logging.exception("Erro ao validar sucesso MP: %s", e)

    # Carrega a polÃ­tica (onde vocÃª colocou logo/imagens, inclusive 'imagem_pagto')
    politica = PoliticaPrivacidade.objects.order_by("-id").first()

    # Monta a URL do vÃ­deo de boas-vindas (o botÃ£o que permanece)
    video_url = reverse("inscricoes:pagina_video_evento", kwargs={"slug": evento.slug})

    context = {
        "inscricao": inscricao,
        "evento": evento,
        "politica": politica,     # usar politica.imagem_pagto no template
        "video_url": video_url,   # usar diretamente no href do botÃ£o
    }
    return render(request, "pagamentos/sucesso.html", context)


@require_GET
def mp_pending(request, inscricao_id):
    """Pagamento pendente/anÃƒÂ¡lise (PIX/boleto, cartÃƒÂ£o em anÃƒÂ¡lise)."""
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    return render(request, "pagamentos/pendente.html", {"inscricao": inscricao})


@require_GET
def mp_failure(request, inscricao_id):
    """Falha/cancelamento. Incentiva tentar novamente."""
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    messages.error(request, "Pagamento nÃƒÂ£o foi concluÃƒÂ­do. VocÃƒÂª pode tentar novamente.")
    return render(request, "pagamentos/falhou.html", {"inscricao": inscricao})


@require_POST
@csrf_exempt
def mp_webhook(request):
    """
    Webhook Mercado Pago tolerante a JSON/form e multi-contas.
    Mantém o atalho de teste local (DEBUG).
    """
    try:
        # DEBUG: atalho de teste local
        if settings.DEBUG:
            try:
                test = (json.loads(request.body or b"{}") or {}).get("test")
            except Exception:
                test = None
            if isinstance(test, dict) and test.get("inscricao_id"):
                inscricao = get_object_or_404(Inscricao, id=test["inscricao_id"])
                status = (test.get("status") or "approved").lower()

                pagamento, _ = Pagamento.objects.get_or_create(
                    inscricao=inscricao,
                    defaults={"valor": inscricao.evento.valor_inscricao}
                )
                if status in ("approved","confirmado"):
                    pagamento.status = Pagamento.StatusPagamento.CONFIRMADO
                    inscricao.pagamento_confirmado = True
                    inscricao.inscricao_concluida = True
                    inscricao.save(update_fields=["pagamento_confirmado","inscricao_concluida"])
                elif status in ("pending","in_process","pendente"):
                    pagamento.status = Pagamento.StatusPagamento.PENDENTE
                else:
                    pagamento.status = Pagamento.StatusPagamento.CANCELADO
                pagamento.transacao_id = str(test.get("id") or "TESTE_LOCAL")
                pagamento.save()
                logging.info("Webhook DEBUG OK: inscricao=%s status=%s", inscricao.id, status)
                return HttpResponse(status=200)

        kind, payment_id = _extract_mp_notification(request)
        if not payment_id:
            logging.warning("Webhook sem payment_id válido. kind=%s", kind)
            return HttpResponse(status=200)

        # 1) Primeiro tenta resolver localmente por transacao_id
        inscricao = _get_inscricao_by_payment_id_local(payment_id)

        payment_json = None
        if not inscricao:
            # 2) Busca no MP (percorrendo credenciais) para descobrir external_reference/metadata
            payment_json = _fetch_payment_with_any_token(payment_id)
            if not payment_json:
                logging.error("Pagamento %s não encontrado em nenhuma credencial.", payment_id)
                return HttpResponse(status=200)

            ext_ref = str(payment_json.get("external_reference") or "").strip()
            meta_inscricao = str(((payment_json.get("metadata") or {}).get("inscricao_id")) or "").strip()
            ref_id = meta_inscricao or ext_ref
            if not ref_id:
                logging.error("Pagamento %s sem external_reference/metadata.inscricao_id.", payment_id)
                return HttpResponse(status=200)
            inscricao = get_object_or_404(Inscricao, id=ref_id)

        # 3) Se ainda não temos o JSON, consulta com a credencial da paróquia correta
        if not payment_json:
            try:
                mp = _mp_client_by_paroquia(inscricao.paroquia)
                resp = mp.payment().get(payment_id) or {}
                payment_json = resp.get("response", {})
            except Exception as e:
                logging.exception("Falha ao consultar pagamento %s: %s", payment_id, e)
                return HttpResponse(status=200)

        # 4) Sincroniza
        try:
            status = _sync_pagamento_from_mp_dict(inscricao, payment_json)
            logging.info("Webhook OK: payment_id=%s inscricao=%s status=%s", payment_id, inscricao.id, status)
        except Exception as e:
            logging.exception("Erro ao sincronizar pagamento %s: %s", payment_id, e)

        return HttpResponse(status=200)

    except Exception as e:
        logging.exception("Erro inesperado no webhook: %s", e)
        return HttpResponse(status=200)



# ===== PÃƒÂ¡gina de contato (sem alteraÃƒÂ§ÃƒÂµes lÃƒÂ³gicas) ===========================

def pagina_de_contato(request):
    paroquia = Paroquia.objects.filter(status='ativa').first()
    context = {'paroquia': paroquia}
    return render(request, 'inscricoes/pagina_de_contato.html', context)

@login_required
def imprimir_todas_fichas(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    inscricoes = Inscricao.objects.filter(
        evento=evento,
        pagamento_confirmado=True
    ).select_related(
        'participante',
        'inscricaosenior','inscricaojuvenil','inscricaomirim','inscricaoservos',
        'conjuge','paroquia'
    )
    return render(request, 'inscricoes/imprimir_todas_fichas.html', {
        'evento': evento,
        'inscricoes': inscricoes,
    })

@login_required
def imprimir_cracha(request, pk):
    insc = get_object_or_404(
        Inscricao.objects.select_related(
            "participante", "evento", "paroquia",
            "alocacao_grupo__grupo",
        ).prefetch_related(
            "alocacao_ministerio",  # se for FK/OneToOne, ok; se ManyToMany, tambÃƒÂ©m funciona
        ),
        pk=pk
    )
    return render(request, "inscricoes/imprimir_cracha.html", {"inscricao": insc})

@login_required
def relatorios_evento(request, evento_id):
    # Busca o evento
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # Opcional: sÃƒÂ³ permite que admin da parÃƒÂ³quia ou superuser acesse
    if not request.user.is_superuser:
        if not hasattr(request.user, 'paroquia') or evento.paroquia != request.user.paroquia:
            return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para ver estes relatÃƒÂ³rios.")

    # Renderiza uma pÃƒÂ¡gina com todos os botÃƒÂµes de relatÃƒÂ³rio
    return render(request, 'inscricoes/relatorios_evento.html', {
        'evento': evento
    })

@login_required
def relatorio_etiquetas_bagagem(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    # PermissÃƒÂ£o: superuser ou mesma parÃƒÂ³quia
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    # Filtro por cidade (query param ?cidade=Ã‚â€¦)
    cidade_sel = request.GET.get('cidade', '').strip()
    inscricoes_qs = Inscricao.objects.filter(
        evento=evento,
        pagamento_confirmado=True,
        inscricao_concluida=True
    ).select_related('participante')

    if cidade_sel:
        inscricoes_qs = inscricoes_qs.filter(
            participante__cidade__iexact=cidade_sel
        )

    # Lista distinta de cidades para o filtro
    cidades = (
        inscricoes_qs
        .values_list('participante__cidade', flat=True)
        .distinct()
        .order_by('participante__cidade')
    )

    # Monta lista de etiquetas (3 por inscriÃƒÂ§ÃƒÂ£o)
    labels = []
    for ins in inscricoes_qs:
        for _ in range(3):
            labels.append(ins)

    return render(request, 'inscricoes/etiquetas_bagagem.html', {
        'evento': evento,
        'labels': labels,
        'cidades': cidades,
        'cidade_sel': cidade_sel,
    })

def _is_admin_geral(user) -> bool:
    return (
        user.is_superuser
        or user.is_staff
        or user.groups.filter(name__in=["AdminGeral", "AdministradorGeral"]).exists()
    )

def _get_base(inscricao):
    """
    Retorna a BaseInscricao (InscricaoSenior/Juvenil/Mirim/Servos) ligada ÃƒÂ  inscriÃƒÂ§ÃƒÂ£o.
    Ajuste os related_names abaixo conforme seu projeto.
    """
    for rel in [
        "inscricaosenior",
        "inscricaojuvenil",
        "inscricaomirim",
        "inscricaoservos",
        "base",  # caso exista um generic/base direto
    ]:
        base = getattr(inscricao, rel, None)
        if base:
            return base
    return None

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

@login_required
def relatorio_ficha_cozinha(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # PermissÃƒÂ£o
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    cidade_sel = (request.GET.get('cidade') or '').strip()

    # Mapeia o subtipo correto do evento
    tipo = (evento.tipo or "").lower()
    Sub = {
        'senior':  InscricaoSenior,
        'juvenil': InscricaoJuvenil,
        'mirim':   InscricaoMirim,
        'servos':  InscricaoServos,
        'casais':  InscricaoCasais,
        'evento':  InscricaoEvento,
        'retiro':  InscricaoRetiro,
    }.get(tipo, InscricaoServos)  # fallback

    # Ã°Å¸â€Å½ Somente pagos + COM alergia a alimento = "sim"
    base_qs = (
        Sub.objects
           .filter(
               inscricao__evento=evento,
               inscricao__pagamento_confirmado=True,
               alergia_alimento__iexact='sim',
           )
           .select_related('inscricao__participante')
           .order_by('inscricao__id')
    )

    if cidade_sel:
        base_qs = base_qs.filter(inscricao__participante__cidade=cidade_sel)

    # Estrutura para o template
    fichas = [{'inscricao': b.inscricao, 'base': b} for b in base_qs]

    # OpÃƒÂ§ÃƒÂµes de cidade (com base no conjunto jÃƒÂ¡ filtrado por alergia)
    cidades = (
        base_qs.values_list('inscricao__participante__cidade', flat=True)
               .distinct()
               .order_by('inscricao__participante__cidade')
    )

    return render(request, 'inscricoes/ficha_cozinha.html', {
        'evento': evento,
        'fichas': fichas,          # <-- jÃƒÂ¡ vem sÃƒÂ³ com alergia alimentar
        'cidades': cidades,
        'cidade_sel': cidade_sel,
    })

@login_required
def relatorio_ficha_farmacia(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    # Mapeia o tipo Ã¢â€ â€™ modelo da base
    tipo = (evento.tipo or "").lower()
    base_map = {
        'senior':  InscricaoSenior,
        'juvenil': InscricaoJuvenil,
        'mirim':   InscricaoMirim,
        'servos':  InscricaoServos,
        'casais':  InscricaoCasais,
        'evento':  InscricaoEvento,
        'retiro':  InscricaoRetiro,
    }
    BaseModel = base_map.get(tipo, InscricaoServos)  # fallback conservador

    # Carrega inscriÃƒÂ§ÃƒÂµes pagas + participante; tenta reduzir hits nas bases
    inscricoes = (
        Inscricao.objects
        .filter(evento=evento, pagamento_confirmado=True)
        .select_related('participante')
    )

    # Dica: se quiser otimizar ainda mais, vocÃƒÂª pode acrescentar um select_related
    # condicional com o nome do OneToOne, ex.: 'inscricaosenior', 'inscricaocasais' etc.
    # related_name padrÃƒÂ£o: <nome_do_modelo_em_minÃƒÂºsculo>
    related_attr = BaseModel.__name__.lower()  # ex.: "inscricaosenior"
    inscricoes = inscricoes.select_related(related_attr)

    fichas = []
    for ins in inscricoes:
        # tenta pegar a base via relaÃƒÂ§ÃƒÂ£o jÃƒÂ¡ carregada; se nÃƒÂ£o existir, busca 1x no banco
        base = getattr(ins, related_attr, None) or BaseModel.objects.filter(inscricao=ins).first()
        if not base:
            continue

        # normaliza Ã¢â‚¬Å“sim/nÃƒÂ£oÃ¢â‚¬Â
        def is_sim(val):
            return (val or "").strip().lower() == "sim"

        # participante aparece se tiver QUALQUER Ã¢â‚¬Å“dado de saÃƒÂºde relevanteÃ¢â‚¬Â
        tem_saude = any([
            is_sim(getattr(base, 'problema_saude', None)),
            bool(getattr(base, 'qual_problema_saude', "")),
            is_sim(getattr(base, 'medicamento_controlado', None)),
            bool(getattr(base, 'qual_medicamento_controlado', "")),
            bool(getattr(base, 'protocolo_administracao', "")),
            is_sim(getattr(base, 'mobilidade_reduzida', None)),
            bool(getattr(base, 'qual_mobilidade_reduzida', "")),
            is_sim(getattr(base, 'alergia_alimento', None)),
            bool(getattr(base, 'qual_alergia_alimento', "")),
            is_sim(getattr(base, 'alergia_medicamento', None)),
            bool(getattr(base, 'qual_alergia_medicamento', "")),
            is_sim(getattr(base, 'diabetes', None)),
            is_sim(getattr(base, 'pressao_alta', None)),
            bool(getattr(base, 'informacoes_extras', "")),
        ])
        if not tem_saude:
            continue

        fichas.append({'inscricao': ins, 'base': base})

    # filtro por cidade
    cidades = sorted({f['inscricao'].participante.cidade for f in fichas if getattr(f['inscricao'].participante, 'cidade', None)})
    cidade_sel = request.GET.get('cidade') or ""
    if cidade_sel:
        fichas = [f for f in fichas if (f['inscricao'].participante.cidade or "") == cidade_sel]

    return render(request, 'inscricoes/ficha_farmacia.html', {
        'evento': evento,
        'fichas': fichas,
        'cidades': cidades,
        'cidade_sel': cidade_sel,
    })

def qr_code_png(request, token):
    """
    Gera um PNG de QR code que aponta para a pÃƒÂ¡gina de inscriÃƒÂ§ÃƒÂ£o
    (ou qualquer endpoint) do participante identificado por `token`.
    """
    participante = get_object_or_404(Participante, qr_token=token)
    # A URL que o QR deve apontar (ajuste para onde quiser redirecionar)
    destino = request.build_absolute_uri(
        reverse('inscricoes:ver_inscricao', args=[participante.id])
    )

    # Gera o QR code
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(destino)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Converte para bytes PNG
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return HttpResponse(buffer, content_type="image/png")

# views.py (adicione abaixo das suas imports jÃƒÂ¡ corrigidas)

def aguardando_pagamento(request, inscricao_id):
    """
    Cria a preferÃªncia no MP e mostra uma pÃ¡gina 'Aguardando pagamento'.
    A pÃ¡gina abre o Checkout em nova aba e comeÃ§a a fazer polling no backend.
    """
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Regras
    if not inscricao.foi_selecionado:
        messages.error(request, "InscriÃ§Ã£o ainda nÃ£o selecionada.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)
    if inscricao.pagamento_confirmado:
        return redirect("inscricoes:mp_success", inscricao.id)

    # Config MP
    try:
        cfg = inscricao.paroquia.mp_config
    except MercadoPagoConfig.DoesNotExist:
        messages.error(request, "Pagamento nÃ£o configurado.")
        return redirect("inscricoes:pagina_de_contato")

    access_token = (cfg.access_token or "").strip()
    if not access_token:
        messages.error(request, "Pagamento nÃ£o configurado.")
        return redirect("inscricoes:pagina_de_contato")

    sdk = mercadopago.SDK(access_token)

    # URLs absolutas no seu domÃ­nio
    sucesso_url = request.build_absolute_uri(reverse("inscricoes:mp_success", args=[inscricao.id]))
    falha_url   = request.build_absolute_uri(reverse("inscricoes:mp_failure", args=[inscricao.id]))
    pend_url    = request.build_absolute_uri(reverse("inscricoes:mp_pending", args=[inscricao.id]))
    # notification_url precisa ser pÃºblico e HTTPS
    webhook_url = _public_https("inscricoes:mp_webhook", _request=request)

    pref_data = {
        "items": [{
            "title": f"InscriÃ§Ã£o â€“ {inscricao.evento.nome}"[:60],
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": float(inscricao.evento.valor_inscricao),
        }],
        "payer": {"email": inscricao.participante.email},
        "external_reference": str(inscricao.id),
        "back_urls": {"success": sucesso_url, "failure": falha_url, "pending": pend_url},
        "auto_return": "approved",               # sÃ³ cartÃ£o aprovado redireciona
        "notification_url": webhook_url,        # webhook Ã© a 'fonte da verdade'
    }

    try:
        mp_pref = sdk.preference().create(pref_data)
        resp = mp_pref.get("response", {}) or {}
        if resp.get("status") == 400 or resp.get("error") or resp.get("message"):
            msg = resp.get("message") or "Falha ao criar preferÃªncia no Mercado Pago."
            if settings.DEBUG:
                return HttpResponse(f"<pre>{resp}</pre>", content_type="text/html")
            messages.error(request, msg)
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        init_point = resp.get("init_point") or resp.get("sandbox_init_point")
        if not init_point:
            messages.error(request, "PreferÃªncia criada sem link de checkout.")
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        # marca/garante pagamento pendente (auditoria)
        Pagamento.objects.update_or_create(
            inscricao=inscricao,
            defaults={
                "valor": inscricao.evento.valor_inscricao,
                "status": Pagamento.StatusPagamento.PENDENTE,
                "metodo": Pagamento.MetodoPagamento.PIX,
            },
        )

        # Renderiza pÃ¡gina que abre o MP em nova aba e faz polling
        return render(request, "pagamentos/aguardando.html", {
            "inscricao": inscricao,
            "init_point": init_point,
        })
    except Exception as e:
        logging.exception("Erro ao criar preferÃªncia MP: %s", e)
        if settings.DEBUG:
            return HttpResponse(f"<pre>{e}</pre>", content_type="text/html")
        messages.error(request, "Erro ao iniciar pagamento.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)


@require_GET
def status_pagamento(request, inscricao_id):
    """
    API simples para o polling no front.
    Retorna o status atual do Pagamento da inscriÃ§Ã£o.
    """
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    pgto = Pagamento.objects.filter(inscricao=inscricao).first()

    status = "pendente"
    if pgto:
        if pgto.status == Pagamento.StatusPagamento.CONFIRMADO:
            status = "confirmado"
        elif pgto.status == Pagamento.StatusPagamento.CANCELADO:
            status = "cancelado"

    return JsonResponse({
        "status": status,
        "pagamento_confirmado": inscricao.pagamento_confirmado,
    })

def _to_decimal(value):
    """Converte com segurança para Decimal, aceitando int/float/str/Decimal."""
    if value is None:
        return None
    try:
        # evita problemas com float binário: sempre converta via str
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def resolve_valor_inscricao(inscricao):
    """
    Tenta resolver o valor da inscrição a partir de múltiplas fontes:
    - campos diretos em Inscricao (valor, valor_total)
    - métodos em Inscricao (get_total, total, calcular_total, valor_total)
    - OneToOne conforme tipo (inscricaosenior, inscricaocasais, etc.)
      olhando por campos comuns (valor, valor_inscricao, taxa, total)
    - Evento (evento.valor, evento.valor_inscricao)

    Lança ValueError se nada for encontrado.
    """
    # 1) Campos diretos em Inscricao
    for field_name in ("valor", "valor_total", "preco", "total"):
        if hasattr(inscricao, field_name):
            val = _to_decimal(getattr(inscricao, field_name))
            if val and val > 0:
                logger.debug("Valor resolvido por Inscricao.%s=%s", field_name, val)
                return val

    # 2) Métodos em Inscricao
    for method_name in ("get_total", "total", "calcular_total", "valor_total"):
        if hasattr(inscricao, method_name) and callable(getattr(inscricao, method_name)):
            try:
                val = _to_decimal(getattr(inscricao, method_name)())
                if val and val > 0:
                    logger.debug("Valor resolvido por Inscricao.%s()=%s", method_name, val)
                    return val
            except Exception as e:
                logger.warning("Falha chamando %s(): %s", method_name, e)

    # 3) OneToOne conforme tipo (com base no que você usa no projeto)
    rels = [
        "inscricaosenior", "inscricaojuvenil", "inscricaomirim",
        "inscricaoservos", "inscricaocasais", "inscricaoevento", "inscricaoretiro",
    ]
    campos_rel = ("valor_total", "valor_inscricao", "valor", "preco", "total", "taxa")
    for rel in rels:
        if hasattr(inscricao, rel):
            obj = getattr(inscricao, rel)
            if obj:
                # campos no objeto relacionado
                for field_name in campos_rel:
                    if hasattr(obj, field_name):
                        val = _to_decimal(getattr(obj, field_name))
                        if val and val > 0:
                            logger.debug("Valor resolvido por %s.%s=%s", rel, field_name, val)
                            return val
                # métodos no objeto relacionado
                for method_name in ("get_total", "calcular_total", "total", "valor_total"):
                    if hasattr(obj, method_name) and callable(getattr(obj, method_name)):
                        try:
                            val = _to_decimal(getattr(obj, method_name)())
                            if val and val > 0:
                                logger.debug("Valor resolvido por %s.%s()=%s", rel, method_name, val)
                                return val
                        except Exception as e:
                            logger.warning("Falha chamando %s.%s(): %s", rel, method_name, e)

    # 4) Evento (fallback)
    if hasattr(inscricao, "evento") and inscricao.evento:
        for field_name in ("valor_inscricao", "valor", "preco", "taxa"):
            if hasattr(inscricao.evento, field_name):
                val = _to_decimal(getattr(inscricao.evento, field_name))
                if val and val > 0:
                    logger.debug("Valor resolvido por Evento.%s=%s", field_name, val)
                    return val

    # Nada encontrado
    # Log detalhado pra debug rápido
    logger.error(
        "Não foi possível resolver o valor da inscrição id=%s. "
        "Verifique campos/métodos disponíveis em Inscricao/relacionados/Evento.",
        getattr(inscricao, "id", None),
    )
    raise ValueError("Não foi possível resolver o valor da inscrição.")

# --- COLE ESTA FUNÇÃO AQUI, ANTES de iniciar_pagamento_pix ---

def get_mp_access_token_from_inscricao(inscricao):
    """
    Retorna (access_token, cfg) do Mercado Pago a partir da Paróquia vinculada à inscrição.
    """
    paroquia = getattr(getattr(inscricao, "evento", None), "paroquia", None) or getattr(inscricao, "paroquia", None)
    if not paroquia:
        raise ValueError("Inscrição sem vínculo de Paróquia (via Evento ou campo direto).")

    try:
        cfg: MercadoPagoConfig = paroquia.mp_config  # related_name="mp_config"
    except ObjectDoesNotExist:
        cfg = None

    token = getattr(cfg, "access_token", None) if cfg else None
    if not token:
        token = getattr(settings, "MP_ACCESS_TOKEN", None)  # fallback opcional

    if not token:
        raise ValueError(
            f"Access Token do Mercado Pago não configurado para a paróquia '{paroquia.nome}' "
            "e não há fallback em settings.MP_ACCESS_TOKEN."
        )

    return token, cfg

def api_pagamento_status(request, inscricao_id):
    i = get_object_or_404(Inscricao, pk=inscricao_id)
    raw = (getattr(i, "status_pagamento", "") or "").lower()

    # Mapeamento unificado -> UI
    if raw in {"approved", "accredited", "paid"}:
        ui = "confirmado"
    elif raw in {"rejected", "cancelled", "canceled"}:
        ui = "cancelado"
    else:
        ui = "pendente"

    return JsonResponse({
        "status": ui,                # <-- usado pelo seu JS do template
        "raw": raw,                  # útil para debug/log
        "pago": ui == "confirmado",
        "payment_id": getattr(i, "payment_id", None),
    })

def iniciar_pagamento_pix(request, inscricao_id):
    """
    Cria cobrança PIX no MP, cria/atualiza Pagamento (PENDENTE) e
    renderiza a página com o QR Code.
    A confirmação virá pelo webhook do MP e atualizará para CONFIRMADO.
    """
    if request.method != "GET":
        return HttpResponseBadRequest("Método não suportado.")

    # 1) Carrega inscrição (+ evento + paróquia)
    ins = get_object_or_404(
        Inscricao.objects.select_related("evento__paroquia"),
        pk=inscricao_id
    )

    # 2) Resolve valor (use seu campo principal; fallback no evento)
    valor = None
    for attr in ("valor", "valor_total", "preco", "total"):
        if hasattr(ins, attr) and getattr(ins, attr):
            valor = Decimal(str(getattr(ins, attr))); break
    if not valor and getattr(ins, "evento", None) and getattr(ins.evento, "valor_inscricao", None):
        valor = Decimal(str(ins.evento.valor_inscricao))
    if not valor or valor <= 0:
        return HttpResponseBadRequest("Valor da inscrição não encontrado.")

    # 3) Pega access token da paróquia (fallback: settings.MP_ACCESS_TOKEN)
    token = None
    try:
        token = ins.evento.paroquia.mp_config.access_token  # OneToOne
    except Exception:
        token = None
    if not token:
        token = getattr(settings, "MP_ACCESS_TOKEN", None)
    if not token:
        return HttpResponseBadRequest("Credenciais do Mercado Pago não configuradas.")

    # 4) Webhook (só envia ao MP se for HTTPS público)
    def https_public(u: str) -> bool:
        try:
            p = urlparse(u); h = (p.hostname or "").lower()
            return p.scheme.lower() == "https" and h not in {"localhost","127.0.0.1","0.0.0.0"} and not h.endswith(".local")
        except Exception:
            return False

    webhook_url = getattr(settings, "PAYMENT_WEBHOOK_URL", None)
    if not webhook_url:
        # usa a rota do seu webhook
        webhook_url = request.build_absolute_uri(reverse("inscricoes:mp_webhook"))
    send_notification = https_public(webhook_url)

    # 5) Cria pagamento PIX no Mercado Pago
    try:
        import mercadopago
        sdk = mercadopago.SDK(token)

        payload = {
            "transaction_amount": float(valor),
            "description": f"Inscrição #{ins.id} — {getattr(getattr(ins,'evento',None),'nome','Evento')}",
            "payment_method_id": "pix",
            "payer": {
                "email": getattr(getattr(ins, "participante", None), "email", None) or "pagador@example.com",
                "first_name": getattr(getattr(ins, "participante", None), "nome", "Participante"),
            },
            "external_reference": str(ins.id),
        }
        if send_notification:
            payload["notification_url"] = webhook_url

        res = sdk.payment().create(payload)
        if res.get("status") not in (200, 201):
            logger.error("Erro ao criar PIX (MP): %s", res)
            return HttpResponseBadRequest("Falha ao criar PIX (Mercado Pago).")

        data = res.get("response") or {}
        tx = (data.get("point_of_interaction") or {}).get("transaction_data") or {}
        qr_code_base64 = tx.get("qr_code_base64")
        qr_code_text   = tx.get("qr_code")
        payment_id     = data.get("id")
        ticket_url     = tx.get("ticket_url") or data.get("ticket_url")
        expires_at     = data.get("date_of_expiration") or (timezone.now() + timedelta(minutes=30)).isoformat()

    except Exception as e:
        logger.exception("Falha Mercado Pago")
        return HttpResponseBadRequest(f"Falha Mercado Pago: {e}")

    # 6) Salva na inscrição (para webhook/polling)
    if payment_id:
        ins.payment_id = str(payment_id)
    ins.status_pagamento = "pending"
    try:
        ins.save(update_fields=["payment_id", "status_pagamento"])
    except Exception:
        pass

    # 7) **Cria/atualiza** o Pagamento AGORA (idempotente)
    pgto, created = Pagamento.objects.get_or_create(
        inscricao=ins,
        defaults={
            "valor": valor,
            "status": Pagamento.StatusPagamento.PENDENTE,  # seu Enum
            "transacao_id": str(payment_id) if payment_id else None,
        },
    )
    mudou = False
    if pgto.valor != valor:
        pgto.valor = valor; mudou = True
    if payment_id and pgto.transacao_id != str(payment_id):
        pgto.transacao_id = str(payment_id); mudou = True
    if pgto.status != Pagamento.StatusPagamento.PENDENTE:
        pgto.status = Pagamento.StatusPagamento.PENDENTE; mudou = True
    if mudou:
        pgto.save()

    # 8) Renderiza a página com o QR (se preferir JSON, troque por JsonResponse)
    ctx = {
        "inscricao": ins,
        "valor": valor,
        "qr_code_base64": qr_code_base64,
        "qr_code_text": qr_code_text,
        "payment_id": payment_id,
        "ticket_url": ticket_url,
        "expires_at": expires_at,
    }
    return render(request, "pagamentos/pix.html", ctx)


def get_webhook_url(request, provider: str = "mp") -> str:
    """
    1) Usa PAYMENT_WEBHOOK_URL do settings (se existir).
    2) Caso contrário, faz reverse da rota do provider.
    3) Fallback para /webhooks/pagamentos/.
    """
    configured = getattr(settings, "PAYMENT_WEBHOOK_URL", None)
    if configured:
        return configured

    route_map = {
        "mp": "inscricoes:mercadopago_webhook",   # AJUSTE ao seu urls.py
        "asaas": "inscricoes:asaas_webhook",      # AJUSTE ao seu urls.py
        "gerencianet": "inscricoes:gerencianet_webhook",  # AJUSTE
        "default": "inscricoes:webhook_pagamento",        # se existir
    }
    name = route_map.get(provider) or route_map["default"]
    try:
        return request.build_absolute_uri(reverse(name))
    except Exception:
        return request.build_absolute_uri("/webhooks/pagamentos/")

import logging
logger = logging.getLogger(__name__)


@require_GET
def status_pagamento(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    pgto = Pagamento.objects.filter(inscricao=inscricao).first()

    status = "pendente"
    if pgto:
        if pgto.status == Pagamento.StatusPagamento.CONFIRMADO:
            status = "confirmado"
        elif pgto.status == Pagamento.StatusPagamento.CANCELADO:
            status = "cancelado"

    return JsonResponse({"status": status, "pagamento_confirmado": inscricao.pagamento_confirmado})

@require_http_methods(["GET", "POST"])
def minhas_inscricoes_por_cpf(request):
    """
    PÃƒÂ¡gina pÃƒÂºblica: participante digita o CPF e vÃƒÂª todas as inscriÃƒÂ§ÃƒÂµes dele.
    Mostra apenas eventos onde foi selecionado, com botÃƒÂµes de pagamento.
    """
    participante = None
    inscricoes = []
    cpf_informado = (request.POST.get("cpf") or request.GET.get("cpf") or "").strip()

    def _buscar_por_cpf(cpf_raw: str):
        """Normaliza e busca inscriÃƒÂ§ÃƒÂµes selecionadas do participante."""
        cpf_limpo = "".join(c for c in (cpf_raw or "") if c.isdigit())
        if len(cpf_limpo) != 11:
            messages.error(request, "Informe um CPF vÃƒÂ¡lido (11 dÃƒÂ­gitos).")
            return None, []
        try:
            p = Participante.objects.get(cpf=cpf_limpo)
        except Participante.DoesNotExist:
            messages.error(request, "CPF nÃƒÂ£o encontrado em nosso sistema.")
            return None, []
        qs = (Inscricao.objects
              .filter(participante=p, foi_selecionado=True)  # <- somente selecionadas
              .select_related("evento", "paroquia")
              .order_by("-id"))
        if not qs.exists():
            messages.info(request, "Nenhuma inscriÃƒÂ§ÃƒÂ£o selecionada encontrada para este CPF.")
        return p, list(qs)

    # Se veio CPF por POST ou por querystring (?cpf=...), tenta buscar
    if cpf_informado:
        participante, inscricoes = _buscar_por_cpf(cpf_informado)

    # Envia a polÃƒÂ­tica pra exibir a logo no topo
    politica = PoliticaPrivacidade.objects.order_by("-id").first()

    return render(request, "inscricoes/minhas_inscricoes.html", {
        "cpf_informado": cpf_informado,
        "participante": participante,
        "inscricoes": inscricoes,
        "politica": politica,
    })

def portal_participante(request):
    participante = None
    inscricoes = []

    if request.method == "POST":
        cpf = (request.POST.get("cpf") or "").replace(".", "").replace("-", "")
        if not cpf.isdigit():
            messages.error(request, "CPF invÃƒÂ¡lido. Digite apenas nÃƒÂºmeros.")
        else:
            participante = Participante.objects.filter(cpf=cpf).first()
            if participante:
                # lista TODAS as inscriÃƒÂ§ÃƒÂµes do participante
                inscricoes = (Inscricao.objects
                               .filter(participante=participante)
                               .select_related("evento","paroquia"))
            else:
                messages.info(request, "Nenhum participante encontrado para este CPF.")

    return render(request, "inscricoes/portal_participante.html", {
        "participante": participante,
        "inscricoes": inscricoes,
        "cpf_informado": request.POST.get("cpf") if request.method == "POST" else "",
    })


@login_required
@user_passes_test(is_admin_geral)
def financeiro_geral(request):
    """
    RelatÃƒÂ³rio consolidado por parÃƒÂ³quia (e breakdown por evento).
    Considera apenas pagamentos CONFIRMADOS.
    Query params:
      ?ini=YYYY-MM-DD&fim=YYYY-MM-DD&paroquia=<id>&fee=5.0
    """
    ini = parse_date(request.GET.get("ini") or "")
    fim = parse_date(request.GET.get("fim") or "")
    paroquia_id = request.GET.get("paroquia") or ""
    fee_param = request.GET.get("fee")
    try:
        fee_percent = Decimal(fee_param) if fee_param is not None else settings.FEE_DEFAULT_PERCENT
    except Exception:
        fee_percent = settings.FEE_DEFAULT_PERCENT

    pagamentos = Pagamento.objects.filter(
        status=Pagamento.StatusPagamento.CONFIRMADO
    ).select_related("inscricao__paroquia", "inscricao__evento")

    # filtros de perÃƒÂ­odo (pela data_pagamento, caindo para data_inscricao se nulo)
    if ini:
        pagamentos = pagamentos.filter(
            Q(data_pagamento__date__gte=ini) | Q(data_pagamento__isnull=True, inscricao__data_inscricao__date__gte=ini)
        )
    if fim:
        pagamentos = pagamentos.filter(
            Q(data_pagamento__date__lte=fim) | Q(data_pagamento__isnull=True, inscricao__data_inscricao__date__lte=fim)
        )
    if paroquia_id:
        pagamentos = pagamentos.filter(inscricao__paroquia_id=paroquia_id)

    # agregado por parÃƒÂ³quia
    por_paroquia = (
        pagamentos.values("inscricao__paroquia_id", "inscricao__paroquia__nome")
        .annotate(
            total_bruto=Sum("valor"),
            qtd=Count("id"),
        )
        .order_by("inscricao__paroquia__nome")
    )

    # breakdown por evento
    por_evento = (
        pagamentos.values(
            "inscricao__paroquia_id", "inscricao__paroquia__nome",
            "inscricao__evento_id", "inscricao__evento__nome"
        )
        .annotate(total_evento=Sum("valor"), qtd_evento=Count("id"))
        .order_by("inscricao__paroquia__nome", "inscricao__evento__nome")
    )

    # monta ÃƒÂ­ndice evento por parÃƒÂ³quia
    eventos_idx = {}
    for row in por_evento:
        pid = row["inscricao__paroquia_id"]
        eventos_idx.setdefault(pid, []).append(row)

    # enriquece com taxa e lÃƒÂ­quido
    linhas = []
    total_geral = Decimal("0.00")
    total_taxa  = Decimal("0.00")
    total_liq   = Decimal("0.00")

    for r in por_paroquia:
        bruto = r["total_bruto"] or Decimal("0.00")
        taxa = (bruto * fee_percent / Decimal("100")).quantize(Decimal("0.01"))
        liq  = (bruto - taxa).quantize(Decimal("0.01"))
        total_geral += bruto
        total_taxa  += taxa
        total_liq   += liq

        linhas.append({
            "paroquia_id": r["inscricao__paroquia_id"],
            "paroquia_nome": r["inscricao__paroquia__nome"],
            "qtd": r["qtd"],
            "bruto": bruto,
            "taxa": taxa,
            "liquido": liq,
            "eventos": eventos_idx.get(r["inscricao__paroquia_id"], [])
        })

    # lista de parÃƒÂ³quias p/ filtro
    todas_paroquias = Paroquia.objects.all().order_by("nome")

    return render(request, "admin_geral/financeiro_geral.html", {
        "linhas": linhas,
        "fee_percent": fee_percent,
        "ini": ini, "fim": fim,
        "paroquia_id": paroquia_id,
        "todas_paroquias": todas_paroquias,
        "totais": {
            "bruto": total_geral,
            "taxa": total_taxa,
            "liquido": total_liq,
        }
    })


@login_required
@user_passes_test(is_admin_geral)
def financeiro_geral_export(request):
    """
    Exporta CSV do relatÃƒÂ³rio consolidado (mesmos filtros da tela).
    """
    ini = parse_date(request.GET.get("ini") or "")
    fim = parse_date(request.GET.get("fim") or "")
    paroquia_id = request.GET.get("paroquia") or ""
    fee_param = request.GET.get("fee")
    try:
        fee_percent = Decimal(fee_param) if fee_param is not None else settings.FEE_DEFAULT_PERCENT
    except Exception:
        fee_percent = settings.FEE_DEFAULT_PERCENT

    pagamentos = Pagamento.objects.filter(
        status=Pagamento.StatusPagamento.CONFIRMADO
    ).select_related("inscricao__paroquia", "inscricao__evento")

    if ini:
        pagamentos = pagamentos.filter(
            Q(data_pagamento__date__gte=ini) | Q(data_pagamento__isnull=True, inscricao__data_inscricao__date__gte=ini)
        )
    if fim:
        pagamentos = pagamentos.filter(
            Q(data_pagamento__date__lte=fim) | Q(data_pagamento__isnull=True, inscricao__data_inscricao__date__lte=fim)
        )
    if paroquia_id:
        pagamentos = pagamentos.filter(inscricao__paroquia_id=paroquia_id)

    por_paroquia = (
        pagamentos.values("inscricao__paroquia_id", "inscricao__paroquia__nome")
        .annotate(total_bruto=Sum("valor"), qtd=Count("id"))
        .order_by("inscricao__paroquia__nome")
    )

    # CSV
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="financeiro_geral.csv"'
    w = csv.writer(resp)
    w.writerow(["ParÃƒÂ³quia", "Qtd Pagamentos", "Total Bruto", f"Taxa ({fee_percent}%)", "LÃƒÂ­quido"])

    for r in por_paroquia:
        bruto = r["total_bruto"] or Decimal("0.00")
        taxa = (bruto * fee_percent / Decimal("100")).quantize(Decimal("0.01"))
        liq  = (bruto - taxa).quantize(Decimal("0.01"))
        w.writerow([r["inscricao__paroquia__nome"], r["qtd"], f"{bruto:.2f}", f"{taxa:.2f}", f"{liq:.2f}"])

    return resp

@csrf_exempt
def whatsapp_webhook(request):
    verify_token = os.getenv("WEBHOOK_VERIFY_TOKEN", "troque-isto")

    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == verify_token:
            return HttpResponse(challenge, status=200)
        return HttpResponse(status=403)

    if request.method == "POST":
        data = json.loads(request.body.decode("utf-8"))
        # aqui vocÃƒÂª pode tratar mensagens e status (entregue/lido/falha)
        return JsonResponse({"ok": True})

    return HttpResponse(status=405)

def editar_politica_reembolso(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    politica, _ = PoliticaReembolso.objects.get_or_create(evento=evento)

    if request.method == 'POST':
        form = PoliticaReembolsoForm(request.POST, instance=politica)
        if form.is_valid():
            form.save()
            messages.success(request, 'PolÃƒÂ­tica de reembolso salva com sucesso.')
            # volte para o painel da parÃƒÂ³quia ou para a lista de eventos Ã‚â€” ajuste se preferir
            return redirect('inscricoes:admin_paroquia_painel', paroquia_id=evento.paroquia_id)
    else:
        form = PoliticaReembolsoForm(instance=politica)

    return render(request, 'inscricoes/editar_politica_reembolso.html', {
        'evento': evento,
        'form': form,
    })

@login_required
def admin_paroquia_create_admin(request):
    # SÃƒÂ³ Admin da ParÃƒÂ³quia (da prÃƒÂ³pria) ou Admin Geral
    if not (hasattr(request.user, "tipo_usuario") and (request.user.is_admin_paroquia() or request.user.is_admin_geral())):
        messages.error(request, "VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para acessar esta pÃƒÂ¡gina.")
        return redirect("inscricoes:home_redirect")

    # ParÃƒÂ³quia Ã‚â€œalvoÃ‚â€:
    # - Admin da parÃƒÂ³quia: sempre a sua
    # - Admin geral: pode usar ?paroquia=<id> (opcional); senÃƒÂ£o, tambÃƒÂ©m usamos a sua
    paroquia = request.user.paroquia
    if request.user.is_admin_geral():
        pid = request.GET.get("paroquia")
        if pid:
            paroquia = get_object_or_404(Paroquia, pk=pid)

    if not paroquia:
        messages.error(request, "Seu usuÃƒÂ¡rio nÃƒÂ£o estÃƒÂ¡ vinculado a uma parÃƒÂ³quia.")
        return redirect("inscricoes:admin_geral_dashboard")

    if request.method == "POST":
        form = AdminParoquiaCreateForm(request.POST)
        if form.is_valid():
            form.save(paroquia=paroquia)
            messages.success(request, "Administrador de parÃƒÂ³quia criado com sucesso.")
            # volta para a mesma pÃƒÂ¡gina (mantendo ?paroquia=) para ver a lista atualizada
            url = reverse("inscricoes:admin_paroquia_create_admin")
            if request.user.is_admin_geral() and request.GET.get("paroquia"):
                url += f"?paroquia={paroquia.id}"
            return redirect(url)
    else:
        form = AdminParoquiaCreateForm()

    # Lista de admins desta parÃƒÂ³quia
    admins = (
        User.objects
            .filter(tipo_usuario="admin_paroquia", paroquia=paroquia)
            .order_by("first_name", "last_name", "username")
    )

    ctx = {
        "form": form,
        "paroquia": paroquia,
        "admins": admins,  # << para o template renderizar a tabela + botÃƒÂ£o Excluir
        "current_year": timezone.now().year,
        "is_admin_geral": request.user.is_admin_geral(),
    }
    return render(request, "inscricoes/admin_paroquia_criar_admin.html", ctx)


@login_required
def admin_paroquia_delete_admin(request, user_id: int):
    if request.method != "POST":
        messages.error(request, "MÃƒÂ©todo invÃƒÂ¡lido.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if not (hasattr(request.user, "tipo_usuario") and (request.user.is_admin_paroquia() or request.user.is_admin_geral())):
        messages.error(request, "VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para esta aÃƒÂ§ÃƒÂ£o.")
        return redirect("inscricoes:home_redirect")

    alvo = get_object_or_404(User, pk=user_id)

    # precisa existir parÃƒÂ³quia no usuÃƒÂ¡rio que executa
    if not request.user.paroquia and not request.user.is_admin_geral():
        messages.error(request, "Seu usuÃƒÂ¡rio nÃƒÂ£o estÃƒÂ¡ vinculado a uma parÃƒÂ³quia.")
        return redirect("inscricoes:admin_geral_dashboard")

    # seguranÃƒÂ§a: sÃƒÂ³ excluir admin_paroquia da MESMA parÃƒÂ³quia
    # (admin geral pode excluir de qualquer parÃƒÂ³quia)
    if alvo.tipo_usuario != "admin_paroquia":
        messages.error(request, "Somente usuÃƒÂ¡rios 'admin_paroquia' podem ser excluÃƒÂ­dos aqui.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if request.user.is_admin_paroquia() and alvo.paroquia_id != request.user.paroquia_id:
        messages.error(request, "VocÃƒÂª nÃƒÂ£o pode excluir um administrador de outra parÃƒÂ³quia.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if alvo.id == request.user.id:
        messages.error(request, "VocÃƒÂª nÃƒÂ£o pode excluir o prÃƒÂ³prio usuÃƒÂ¡rio.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    nome = alvo.get_full_name() or alvo.username
    alvo.delete()
    messages.success(request, f"Administrador '{nome}' excluÃƒÂ­do com sucesso.")

    # preservar ?paroquia= para admin geral
    url = reverse("inscricoes:admin_paroquia_create_admin")
    if request.user.is_admin_geral() and request.GET.get("paroquia"):
        url += f"?paroquia={request.GET.get('paroquia')}"
    return redirect(url)

try:
    from .finance_calc import calcular_financeiro_evento as _calc_financeiro_evento_external
except Exception:
    _calc_financeiro_evento_external = None


# ===== CÃƒÂLCULO FINANCEIRO (com fallback) =====
TAXA_SISTEMA_DEFAULT = Decimal("3.00")

def calcular_financeiro_evento(evento, taxa_percentual=TAXA_SISTEMA_DEFAULT):
    """
    Se existir .finance_calc, delega para lÃƒÂ¡. Caso contrÃƒÂ¡rio,
    calcula aqui com base nos Pagamentos confirmados do evento.
    """
    if _calc_financeiro_evento_external:
        return _calc_financeiro_evento_external(evento, taxa_percentual)

    pagos = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO
    )

    bruto = pagos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")

    # taxa do MP (se a coluna fee_mp existir)
    try:
        Pagamento._meta.get_field("fee_mp")
        taxas_mp = pagos.aggregate(total=Sum("fee_mp"))["total"] or Decimal("0.00")
    except FieldDoesNotExist:
        taxas_mp = Decimal("0.00")

    base = (bruto - taxas_mp).quantize(Decimal("0.01"))
    taxa = (base * Decimal(taxa_percentual) / Decimal("100")).quantize(Decimal("0.01"))
    liquido_paroquia = (base - taxa).quantize(Decimal("0.01"))

    return {
        "bruto": bruto,
        "taxas_mp": taxas_mp,
        "base_repasse": base,
        "taxa_percent": Decimal(taxa_percentual),
        "valor_repasse": taxa,
        "liquido_paroquia": liquido_paroquia,
    }


# ===== LISTA DE EVENTOS (REPASSES) =====
@login_required
@user_passes_test(lambda u: u.is_admin_paroquia())
def repasse_lista_eventos(request):
    paroquia = request.user.paroquia
    eventos = (EventoAcampamento.objects
               .filter(paroquia=paroquia)
               .order_by("-data_inicio"))

    # verifica se o campo fee_mp existe no modelo Pagamento
    has_fee_mp = True
    try:
        Pagamento._meta.get_field("fee_mp")
    except FieldDoesNotExist:
        has_fee_mp = False

    linhas = []
    for ev in eventos:
        pagos = Pagamento.objects.filter(
            inscricao__evento=ev,
            status=Pagamento.StatusPagamento.CONFIRMADO
        )
        bruto = pagos.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")

        if has_fee_mp:
            taxas_mp = pagos.aggregate(total=Sum("fee_mp"))["total"] or Decimal("0.00")
        else:
            taxas_mp = Decimal("0.00")  # sem a coluna fee_mp

        linhas.append({
            "evento": ev,
            "bruto": bruto,
            "taxas_mp": taxas_mp,
            "detalhe_url": reverse("inscricoes:repasse_evento_detalhe", args=[ev.id]),
            "sem_fee_mp": not has_fee_mp,
        })

    return render(request, "financeiro/repasse_lista_eventos.html", {"linhas": linhas})


# ===== DETALHE DO EVENTO (REPASSE) =====
@login_required
@user_passes_test(lambda u: u.is_admin_paroquia())
def repasse_evento_detalhe(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id, paroquia=request.user.paroquia)
    fin = calcular_financeiro_evento(evento)

    historico = (Repasse.objects
                 .filter(evento=evento, paroquia=request.user.paroquia)
                 .order_by("-criado_em"))

    return render(request, "financeiro/repasse_evento_detalhe.html", {
        "evento": evento,
        "fin": fin,
        "historico": historico,
    })


# ===== GERAR PIX DO REPASSE =====
@login_required
@user_passes_test(lambda u: u.is_admin_paroquia())
def gerar_pix_repasse_evento(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id, paroquia=request.user.paroquia)
    fin = calcular_financeiro_evento(evento)
    valor = float(fin["valor_repasse"])

    if valor <= 0:
        messages.error(request, "NÃƒÂ£o hÃƒÂ¡ valor a repassar para este evento.")
        return redirect("inscricoes:repasse_evento_detalhe", evento_id=evento.id)

    try:
        sdk, cfg = mp_owner_client()
    except Exception as e:
        messages.error(request, f"ConfiguraÃƒÂ§ÃƒÂ£o do Mercado Pago (DONO) ausente/invÃƒÂ¡lida: {e}")
        return redirect("inscricoes:repasse_evento_detalhe", evento_id=evento.id)

    notification_url = (cfg.notificacao_webhook_url or "").strip()

    with transaction.atomic():
        # Reutiliza (lock) ou cria um ÃƒÂºnico repasse pendente por evento
        repasse = (Repasse.objects
                   .select_for_update()
                   .filter(paroquia=request.user.paroquia,
                           evento=evento,
                           status=Repasse.Status.PENDENTE)
                   .first())

        if not repasse:
            repasse = Repasse.objects.create(
                paroquia=request.user.paroquia,
                evento=evento,
                valor_base=fin["base_repasse"],
                taxa_percentual=fin["taxa_percent"],
                valor_repasse=fin["valor_repasse"],
                status=Repasse.Status.PENDENTE,
            )
        else:
            # atualiza valores (se mudou algo desde a criaÃƒÂ§ÃƒÂ£o)
            repasse.valor_base = fin["base_repasse"]
            repasse.taxa_percentual = fin["taxa_percent"]
            repasse.valor_repasse = fin["valor_repasse"]

        body = {
            "transaction_amount": float(repasse.valor_repasse),
            "description": f"Repasse taxa sistema Ã‚â€“ {evento.nome}",
            "payment_method_id": "pix",
            "payer": {
                "email": (request.user.email or cfg.email_cobranca or "repasse@dominio.local")
            },
            "external_reference": f"repasse:{request.user.paroquia_id}:{evento.id}",
        }
        if notification_url:
            body["notification_url"] = notification_url

        try:
            resp = sdk.payment().create(body).get("response", {}) or {}
            pio = (resp.get("point_of_interaction") or {})
            tx = (pio.get("transaction_data") or {})

            repasse.transacao_id = str(resp.get("id") or "")
            repasse.qr_code_text = tx.get("qr_code")
            repasse.qr_code_base64 = tx.get("qr_code_base64")
            repasse.save()

            messages.success(request, "PIX de repasse gerado/atualizado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao gerar PIX: {e}")

    return redirect("inscricoes:repasse_evento_detalhe", evento_id=evento.id)


# ===== WEBHOOK DO DONO (REPASSES) =====
@csrf_exempt
def mp_owner_webhook(request):
    """
    Webhook exclusivo para pagamentos de REPASSE (conta do DONO).
    Atualiza o status do Repasse com base no payment_id recebido.
    """
    try:
        payload = json.loads(request.body or "{}")
        payment_id = (payload.get("data") or {}).get("id") or payload.get("id")
        if not payment_id:
            return HttpResponse(status=200)

        sdk, _ = mp_owner_client()
        payment = sdk.payment().get(payment_id).get("response", {})
        ext = (payment.get("external_reference") or "")
        # Formato esperado: repasse:<paroquia_id>:<evento_id>
        if not ext.startswith("repasse:"):
            return HttpResponse(status=200)

        parts = ext.split(":")
        if len(parts) != 3:
            return HttpResponse(status=200)

        paroquia_id, evento_id = parts[1], parts[2]

        rep = Repasse.objects.filter(transacao_id=str(payment.get("id") or "")).first()
        if not rep:
            rep = (Repasse.objects
                   .filter(paroquia_id=paroquia_id, evento_id=evento_id, status=Repasse.Status.PENDENTE)
                   .order_by("-criado_em").first())
        if not rep:
            return HttpResponse(status=200)

        status = (payment.get("status") or "").lower()
        if status == "approved":
            rep.status = Repasse.Status.PAGO
        elif status in ("pending", "in_process"):
            rep.status = Repasse.Status.PENDENTE
        else:
            rep.status = Repasse.Status.CANCELADO

        rep.save(update_fields=["status", "atualizado_em"])
        return HttpResponse(status=200)
    except Exception:
        # NÃƒÂ£o quebrar o fluxo de callbacks
        return HttpResponse(status=200)

class LoginComImagemView(LoginView):
    template_name = "inscricoes/login.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["politica"] = PoliticaPrivacidade.objects.order_by("-id").first()
        return ctx
    
@login_required
def video_evento_form(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)

    # PermissÃƒÂ£o bÃƒÂ¡sica: admin geral ou admin da mesma parÃƒÂ³quia
    if not (getattr(request.user, "is_superuser", False)
            or (hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral())
            or (hasattr(request.user, "is_admin_paroquia") and request.user.is_admin_paroquia()
                and request.user.paroquia_id == evento.paroquia_id)):
        return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para editar este evento.")

    # OneToOne: pega existente ou None
    try:
        video = evento.video
    except VideoEventoAcampamento.DoesNotExist:
        video = None

    if request.method == "POST":
        form = VideoEventoForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.evento = evento
            obj.save()
            messages.success(request, "VÃƒÂ­deo do evento salvo com sucesso!")
            # redirecione para a prÃƒÂ³pria pÃƒÂ¡gina ou para o detalhe do evento
            return redirect("inscricoes:video_evento_form", slug=slug)
        else:
            messages.error(request, "Por favor, corrija os erros abaixo.")
    else:
        form = VideoEventoForm(instance=video)

    return render(request, "inscricoes/video_evento_form.html", {
        "evento": evento,
        "form": form,
        "video": video,
    })

from django.views.decorators.cache import never_cache
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

@never_cache
def painel_sorteio(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    agora = timezone.localtime()
    context = {
        "evento": evento,
        "server_now_iso": agora.isoformat(),
        "server_date": agora.strftime("%d/%m/%Y"),
        "server_time": agora.strftime("%H:%M:%S"),
    }
    return render(request, "inscricoes/painel_sorteio.html", context)

@never_cache
def api_selecionados(request, slug):
    """
    Retorna todos os selecionados do evento.
    - Eventos 'casais': item ÃƒÂºnico por par -> {"casal": true, "foto_casal": <url?>, "p1": {...}, "p2": {...}}
    - Demais: itens individuais {"id":..., "nome":..., "foto_casal": <url?>}
    OrdenaÃƒÂ§ÃƒÂ£o crescente por id para que o ÃƒÂºltimo seja o mais recente.
    """
    evento = get_object_or_404(EventoAcampamento, slug=slug)

    qs = (
        Inscricao.objects
        .select_related(
            "participante", "evento",
            "inscricao_pareada__participante",
            "pareada_por__participante",
            # Ã°Å¸â€˜â€¡ inclui a base de casais para recuperar foto_casal sem novo hit
            "inscricaocasais",
            "inscricao_pareada__inscricaocasais",
            "pareada_por__inscricaocasais",
        )
        .filter(evento=evento, foi_selecionado=True)
        .order_by("id")
    )

    def serializa_part(i: Inscricao) -> dict:
        p = i.participante

        # Foto individual (CloudinaryField em Participante.foto)
        foto_url = None
        try:
            f = getattr(p, "foto", None)
            if f:
                foto_url = f.url
        except Exception:
            foto_url = None

        # Foto do casal (ImageField em InscricaoCasais.foto_casal)
        foto_casal_url = None
        try:
            base_casal = getattr(i, "inscricaocasais", None)
            if base_casal and getattr(base_casal, "foto_casal", None):
                if base_casal.foto_casal:
                    foto_casal_url = base_casal.foto_casal.url
        except Exception:
            foto_casal_url = None

        return {
            "id": i.id,
            "nome": p.nome,
            "cidade": getattr(p, "cidade", "") or "",
            "estado": getattr(p, "estado", "") or "",
            "foto": foto_url,             # foto individual (se houver)
            "foto_casal": foto_casal_url, # foto do casal (se houver)
        }

    data = []

    if (evento.tipo or "").lower() == "casais":
        vistos = set()
        pares = []
        avulsos = []

        for i in qs:
            par = i.par
            if par and par.foi_selecionado and par.evento_id == i.evento_id:
                key = tuple(sorted([i.id, par.id]))
                if key in vistos:
                    continue
                vistos.add(key)

                p1 = serializa_part(i)
                p2 = serializa_part(par)

                # Ã°Å¸Å½Â¯ no objeto raiz do casal, expÃƒÂµe foto_casal (prioridade p1 Ã¢â€ â€™ p2)
                foto_casal_root = p1.get("foto_casal") or p2.get("foto_casal") or None

                rank = max(i.id, par.id)
                pares.append((
                    rank,
                    {
                        "casal": True,
                        "foto_casal": foto_casal_root,
                        "p1": p1,
                        "p2": p2,
                    }
                ))
            else:
                avulsos.append((i.id, serializa_part(i)))

        pares.sort(key=lambda t: t[0])
        avulsos.sort(key=lambda t: t[0])
        data = [d for _, d in pares] + [d for _, d in avulsos]
    else:
        data = [serializa_part(i) for i in qs]

    return JsonResponse({
        "selecionados": data,
        "generated_at": timezone.now().isoformat(),
        "count": len(data),
    })


# --- LANDING + CONTATO (UNIFICADO) ------------------------------------------
from typing import Any, Dict, Optional

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import LeadLandingForm
from .models import Paroquia, EventoAcampamento, LeadLanding, SiteVisit


# --------------------- helpers ---------------------
def _has_field(model, name: str) -> bool:
    return name in {f.name for f in model._meta.get_fields() if hasattr(f, "name")}

def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""

def _paroquia_from_request(request: HttpRequest) -> Optional[Paroquia]:
    pid = request.GET.get("paroquia")
    if not pid:
        return None
    try:
        return Paroquia.objects.get(pk=int(pid))
    except Exception:
        return None

def _landing_context(request: HttpRequest, form: LeadLandingForm) -> Dict[str, Any]:
    # registra visita (nÃƒÂ£o falha se o modelo nÃƒÂ£o existir)
    try:
        SiteVisit.objects.create(
            path=request.get_full_path(),
            ip=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        )
    except Exception:
        pass

    hoje = timezone.localdate()
    paroquia_atual = _paroquia_from_request(request)

    # Eventos com inscriÃƒÂ§ÃƒÂµes abertas
    qs = EventoAcampamento.objects.all()
    if paroquia_atual and _has_field(EventoAcampamento, "paroquia"):
        qs = qs.filter(paroquia=paroquia_atual)
    if _has_field(EventoAcampamento, "inicio_inscricoes"):
        qs = qs.filter(Q(inicio_inscricoes__isnull=True) | Q(inicio_inscricoes__lte=hoje))
    if _has_field(EventoAcampamento, "fim_inscricoes"):
        qs = qs.filter(Q(fim_inscricoes__isnull=True) | Q(fim_inscricoes__gte=hoje))
    if _has_field(EventoAcampamento, "publico"):
        qs = qs.filter(publico=True)
    if _has_field(EventoAcampamento, "ativo"):
        qs = qs.filter(ativo=True)

    eventos_abertos = qs.order_by("data_inicio")[:12]

    # Blocos de comunidade (opcionais)
    comunicados = []
    try:
        from .models import Comunicado  # type: ignore
        cqs = Comunicado.objects.all()
        if paroquia_atual and _has_field(Comunicado, "paroquia"):
            cqs = cqs.filter(paroquia=paroquia_atual)
        if _has_field(Comunicado, "publicado"):
            cqs = cqs.filter(publicado=True)
        if _has_field(Comunicado, "data_publicacao"):
            cqs = cqs.order_by("-data_publicacao")
        comunicados = list(cqs[:10])
    except Exception:
        pass

    eventos_comunidade = []
    try:
        from .models import EventoComunitario  # type: ignore
        ecqs = EventoComunitario.objects.all()
        if paroquia_atual and _has_field(EventoComunitario, "paroquia"):
            ecqs = ecqs.filter(paroquia=paroquia_atual)
        if _has_field(EventoComunitario, "visivel_site"):
            ecqs = ecqs.filter(visivel_site=True)
        if _has_field(EventoComunitario, "data_inicio"):
            ecqs = ecqs.order_by("data_inicio")
        eventos_comunidade = list(ecqs[:10])
    except Exception:
        pass

    return {
        "form": form,
        "eventos_abertos": eventos_abertos,
        "comunicados": comunicados,
        "eventos_comunidade": eventos_comunidade,
        "paroquia_atual": paroquia_atual,
    }


# --------------------- views ---------------------
def landing(request: HttpRequest) -> HttpResponse:
    """
    PÃƒÂ¡gina pÃƒÂºblica de entrada.
    Template: inscricoes/site_eismeaqui.html
    """
    form = LeadLandingForm()
    ctx = _landing_context(request, form)
    return render(request, "inscricoes/site_eismeaqui.html", ctx)


@require_POST
def contato_enviar(request: HttpRequest) -> HttpResponse:
    """
    Processa o formulÃƒÂ¡rio de contato da landing.
    Re-renderiza a mesma landing com erros (status 400) ou redireciona com sucesso.
    """
    form = LeadLandingForm(request.POST)
    if not form.is_valid():
        ctx = _landing_context(request, form)
        messages.error(request, "Verifique os campos destacados e tente novamente.")
        return render(request, "inscricoes/site_eismeaqui.html", ctx, status=400)

    nome = form.cleaned_data["nome"]
    email = form.cleaned_data["email"]
    whatsapp = form.cleaned_data.get("whatsapp", "")
    mensagem = form.cleaned_data.get("mensagem", "")

    # Salva lead (se o modelo existir)
    try:
        LeadLanding.objects.create(
            nome=nome,
            email=email,
            whatsapp=whatsapp,
            mensagem=mensagem,
            origem="landing",
            ip=_client_ip(request),
            consent_lgpd=form.cleaned_data.get("lgpd", False),
        )
    except Exception:
        pass

    # E-mail para admin
    try:
        assunto_admin = f"[eismeaqui] Novo contato: {nome}"
        texto_admin = (
            f"Nome: {nome}\nWhatsApp: {whatsapp}\nE-mail: {email}\n\nMensagem:\n{mensagem}"
        )
        msg_admin = EmailMultiAlternatives(
            assunto_admin,
            texto_admin,
            settings.DEFAULT_FROM_EMAIL,
            [getattr(settings, "CONTACT_EMAIL", settings.DEFAULT_FROM_EMAIL)],
        )
        msg_admin.send(fail_silently=True)
    except Exception:
        pass

    # E-mail de confirmaÃƒÂ§ÃƒÂ£o ao usuÃƒÂ¡rio
    try:
        assunto_user = "Recebemos sua mensagem Ã‚â€“ eismeaqui.app"
        texto_user = (
            f"OlÃƒÂ¡ {nome},\n\nRecebemos sua mensagem e entraremos em contato em breve.\n\n"
            f"Resumo enviado:\nWhatsApp: {whatsapp}\nMensagem: {mensagem}\n\n"
            "Deus abenÃƒÂ§oe!\nEquipe eismeaqui.app"
        )
        msg_user = EmailMultiAlternatives(
            assunto_user,
            texto_user,
            settings.DEFAULT_FROM_EMAIL,
            [email],
        )
        msg_user.send(fail_silently=True)
    except Exception:
        pass

    messages.success(request, "Recebemos sua mensagem! Em breve retornaremos.")
    return redirect(reverse("inscricoes:landing") + "#contato")

# inscricoes/views.py
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages

from .models import Comunicado, Paroquia
from .forms import ComunicadoForm

def _user_is_admin_paroquia(user):
    return user.is_authenticated and hasattr(user, "is_admin_paroquia") and user.is_admin_paroquia()

def _user_is_admin_geral(user):
    return user.is_authenticated and (
        getattr(user, "is_superuser", False) or
        getattr(user, "tipo_usuario", "") == "admin_geral" or
        (hasattr(user, "is_admin_geral") and user.is_admin_geral())
    )

@login_required
def publicacoes_list(request):
    """
    Lista publicaÃƒÂ§ÃƒÂµes da parÃƒÂ³quia do usuÃƒÂ¡rio (admin paroquia) ou,
    para admin geral, aceita ?paroquia=<id> para filtrar.
    """
    if _user_is_admin_geral(request.user):
        pid = request.GET.get("paroquia") or getattr(request.user, "paroquia_id", None)
        paroquia = get_object_or_404(Paroquia, pk=pid) if pid else getattr(request.user, "paroquia", None)
    elif _user_is_admin_paroquia(request.user):
        paroquia = getattr(request.user, "paroquia", None)
        if not paroquia:
            messages.error(request, "Sua conta nÃƒÂ£o estÃƒÂ¡ vinculada a uma parÃƒÂ³quia.")
            return redirect("inscricoes:home_redirect")
    else:
        messages.error(request, "Sem permissÃƒÂ£o.")
        return redirect("inscricoes:home_redirect")

    items = Comunicado.objects.filter(paroquia=paroquia).order_by("-data_publicacao", "-id")
    return render(request, "inscricoes/publicacoes_list.html", {
        "paroquia": paroquia,
        "items": items,
    })

@login_required
def publicacao_criar(request):
    if _user_is_admin_geral(request.user):
        paroquia = getattr(request.user, "paroquia", None)
        pid = request.GET.get("paroquia")
        if pid:
            paroquia = get_object_or_404(Paroquia, pk=pid)
    elif _user_is_admin_paroquia(request.user):
        paroquia = getattr(request.user, "paroquia", None)
        if not paroquia:
            messages.error(request, "Sua conta nÃƒÂ£o estÃƒÂ¡ vinculada a uma parÃƒÂ³quia.")
            return redirect("inscricoes:home_redirect")
    else:
        messages.error(request, "Sem permissÃƒÂ£o.")
        return redirect("inscricoes:home_redirect")

    if request.method == "POST":
        form = ComunicadoForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.paroquia = paroquia
            obj.save()
            messages.success(request, "PublicaÃƒÂ§ÃƒÂ£o criada com sucesso!")
            return redirect("inscricoes:publicacoes_list")
    else:
        form = ComunicadoForm()

    return render(request, "inscricoes/publicacao_form.html", {
        "form": form,
        "paroquia": paroquia,
        "is_edit": False,
    })

@login_required
def publicacao_editar(request, pk: int):
    obj = get_object_or_404(Comunicado, pk=pk)
    # permissÃƒÂ£o: admin da mesma parÃƒÂ³quia ou admin geral
    if not _user_is_admin_geral(request.user):
        if not _user_is_admin_paroquia(request.user) or request.user.paroquia_id != obj.paroquia_id:
            messages.error(request, "Sem permissÃƒÂ£o para editar esta publicaÃƒÂ§ÃƒÂ£o.")
            return redirect("inscricoes:publicacoes_list")

    if request.method == "POST":
        form = ComunicadoForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "PublicaÃƒÂ§ÃƒÂ£o atualizada!")
            return redirect("inscricoes:publicacoes_list")
    else:
        form = ComunicadoForm(instance=obj)

    return render(request, "inscricoes/publicacao_form.html", {
        "form": form,
        "paroquia": obj.paroquia,
        "is_edit": True,
        "obj": obj,
    })

@login_required
def publicacao_excluir(request, pk: int):
    obj = get_object_or_404(Comunicado, pk=pk)
    if not _user_is_admin_geral(request.user):
        if not _user_is_admin_paroquia(request.user) or request.user.paroquia_id != obj.paroquia_id:
            messages.error(request, "Sem permissÃƒÂ£o para excluir esta publicaÃƒÂ§ÃƒÂ£o.")
            return redirect("inscricoes:publicacoes_list")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "PublicaÃƒÂ§ÃƒÂ£o excluÃƒÂ­da.")
        return redirect("inscricoes:publicacoes_list")

    return render(request, "inscricoes/publicacao_confirm_delete.html", {"obj": obj})

def comunicado_detalhe(request, pk: int):
    from .models import Comunicado  # evita import circular
    obj = get_object_or_404(Comunicado, pk=pk)
    # se tiver flag publicado e quiser ocultar os nÃƒÂ£o publicados:
    try:
        if hasattr(obj, "publicado") and not obj.publicado:
            # admin pode visualizar, pÃƒÂºblico nÃƒÂ£o
            if not request.user.is_authenticated:
                from django.http import Http404
                raise Http404()
    except Exception:
        pass
    return render(request, "inscricoes/comunicado_detalhe.html", {"c": obj})

from datetime import date
from django.shortcuts import render, get_object_or_404
from django.db.models import Q, Count, OuterRef, Subquery, IntegerField, Value, CharField, Case, When
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date

def admin_paroquia_eventos(request, pk):
    paroquia = get_object_or_404(Paroquia, pk=pk)

    # ---- Filtros GET
    q      = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip().upper()   # "ABERTO" | "FECHADO" | "ENCERRADO"
    tipo   = (request.GET.get("tipo") or "").strip()
    de     = parse_date(request.GET.get("de") or "")
    ate    = parse_date(request.GET.get("ate") or "")

    hoje = date.today()

    # ---- Query base
    qs = (
        EventoAcampamento.objects
        .filter(paroquia=paroquia)
        .select_related("paroquia")
        .order_by("-data_inicio")
    )

    # ---- Filtros
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(slug__icontains=q))
    if tipo:
        qs = qs.filter(tipo=tipo)
    if de:
        qs = qs.filter(data_inicio__gte=de)
    if ate:
        qs = qs.filter(data_inicio__lte=ate)

    # Status (via datas, pois 'status_inscricao' ÃƒÂ© property)
    if status == "ABERTO":
        qs = qs.filter(inicio_inscricoes__lte=hoje, fim_inscricoes__gte=hoje)
    elif status == "FECHADO":
        qs = qs.filter(inicio_inscricoes__gt=hoje)
    elif status == "ENCERRADO":
        qs = qs.filter(fim_inscricoes__lt=hoje)

    # ---- Subqueries (independe de related_name)
    inscritos_sq = (
        Inscricao.objects
        .filter(evento=OuterRef("pk"))
        .values("evento")
        .annotate(c=Count("id"))
        .values("c")[:1]
    )
    confirmados_sq = (
        Inscricao.objects
        .filter(evento=OuterRef("pk"), pagamento_confirmado=True)
        .values("evento")
        .annotate(c=Count("id"))
        .values("c")[:1]
    )

    # ---- AnotaÃƒÂ§ÃƒÂµes + status_code para usar na UI se quiser
    qs = qs.annotate(
        total_inscritos=Coalesce(Subquery(inscritos_sq, output_field=IntegerField()), Value(0)),
        total_confirmados=Coalesce(Subquery(confirmados_sq, output_field=IntegerField()), Value(0)),
        status_code=Case(
            When(inicio_inscricoes__lte=hoje, fim_inscricoes__gte=hoje, then=Value("ABERTO")),
            When(inicio_inscricoes__gt=hoje, then=Value("FECHADO")),
            default=Value("ENCERRADO"),
            output_field=CharField(),
        ),
    )

    # ---- PaginaÃƒÂ§ÃƒÂ£o
    paginator  = Paginator(qs, 12)
    page_obj   = paginator.get_page(request.GET.get("page"))
    eventos_pg = page_obj.object_list

    # ---- KPIs (gerais da parÃƒÂ³quia)
    # InscriÃƒÂ§ÃƒÂµes totais/confirmadas por parÃƒÂ³quia
    insc_paroquia = Inscricao.objects.filter(evento__paroquia=paroquia)
    total_inscricoes = insc_paroquia.count()
    total_inscricoes_confirmadas = insc_paroquia.filter(pagamento_confirmado=True).count()

    # KPIs de eventos (base no queryset jÃƒÂ¡ filtrado)
    total_eventos = paginator.count
    eventos_abertos = qs.filter(inicio_inscricoes__lte=hoje, fim_inscricoes__gte=hoje).count()

    # Tipos para o <select>
    try:
        tipos_evento = EventoAcampamento.TIPO_ACAMPAMENTO
    except AttributeError:
        tipos_evento = []

    ctx = {
        "paroquia": paroquia,
        "eventos": eventos_pg,
        "is_paginated": page_obj.has_other_pages(),
        "page_obj": page_obj,
        "paginator": paginator,

        # KPIs sidebar
        "total_eventos": total_eventos,
        "eventos_abertos": eventos_abertos,
        "total_inscricoes": total_inscricoes,
        "total_inscricoes_confirmadas": total_inscricoes_confirmadas,

        "tipos_evento": tipos_evento,
    }
    return render(request, "inscricoes/evento_list.html", ctx)

def _pode_gerir_inscricao(user, inscricao: Inscricao) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "tipo_usuario", "") == "admin_geral":
        return True
    # admin da prÃƒÂ³pria parÃƒÂ³quia
    return getattr(user, "paroquia_id", None) == inscricao.paroquia_id

@login_required
@require_POST
def toggle_selecao_inscricao(request, pk: int):
    insc = get_object_or_404(Inscricao, pk=pk)

    if not _pode_gerir_inscricao(request.user, insc):
        return HttpResponseForbidden("Sem permissão.")

    # esperado: selected="true" | "false"
    selected_raw = (request.POST.get("selected") or "").lower().strip()
    selected = selected_raw in ("1", "true", "t", "on", "yes", "y")

    # Regras:
    # - Selecionado => status CONVOCADA (não gera pagamento aqui)
    # - Desselecionado => status EM_ANALISE
    novo_status = InscricaoStatus.CONVOCADA if selected else InscricaoStatus.EM_ANALISE

    # pagamento_confirmado só é True quando status == PAG_CONFIRMADO
    novo_pagto_confirmado = (novo_status == InscricaoStatus.PAG_CONFIRMADO)

    par = _find_pair_in_same_event(insc)

    with transaction.atomic():
        updates = []

        if insc.foi_selecionado != selected:
            insc.foi_selecionado = selected
            updates.append("foi_selecionado")

        if insc.status != novo_status:
            insc.status = novo_status
            updates.append("status")

        # mantém consistência do badge/flag local
        if getattr(insc, "pagamento_confirmado", False) != novo_pagto_confirmado:
            insc.pagamento_confirmado = novo_pagto_confirmado
            updates.append("pagamento_confirmado")

        if updates:
            insc.save(update_fields=updates)

        # Se houver par, espelha SOMENTE a seleção (não mexe em status/pagamento do par)
        if par and par.foi_selecionado != selected:
            par.foi_selecionado = selected
            par.save(update_fields=["foi_selecionado"])

    return JsonResponse({
        "ok": True,
        "inscricao_id": insc.id,
        "selected": bool(insc.foi_selecionado),
        "changed": bool(updates),  # True se alterou algo
        "status": insc.status,
        "label": insc.get_status_display(),
        "pagamento_confirmado": bool(getattr(insc, "pagamento_confirmado", False)),
        "msg": "Participante selecionado" if insc.foi_selecionado else "Participante desmarcado",
    })
from django.db.models import Q, Count

@login_required
def inscricao_ficha_geral(request, pk: int):
    qs = (
        Inscricao.objects
        .select_related("participante", "evento", "paroquia")
        .prefetch_related(
            "contatos",
            "filhos",
            "alocacao_grupo__grupo",
            "alocacao_ministerio__ministerio",
        )
    )
    inscricao = get_object_or_404(qs, pk=pk)

    # PermissÃƒÂ£o: superuser/admin_geral vÃƒÂª tudo; admin_paroquia sÃƒÂ³ da prÃƒÂ³pria parÃƒÂ³quia
    u = request.user
    if (not getattr(u, "is_superuser", False)
        and getattr(u, "tipo_usuario", "") != "admin_geral"
        and getattr(u, "paroquia_id", None) != inscricao.paroquia_id):
        return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para ver esta inscriÃƒÂ§ÃƒÂ£o.")

    # MinistÃƒÂ©rios sÃƒÂ³ para evento do tipo "servos"
    ministerios = []
    if (inscricao.evento.tipo or "").lower() == "servos":
        ministerios = list(
            Ministerio.objects.filter(ativo=True)
            .order_by("nome")
        )

    # Grupos: AGORA SEMPRE (catÃƒÂ¡logo global)
    # Se quiser limitar aos grupos Ã‚â€œusadosÃ‚â€ neste evento, troque por:
    # grupos = (Grupo.objects
    #           .filter(alocacoes__inscricao__evento=inscricao.evento)
    #           .distinct().order_by("nome"))
    grupos = list(
        Grupo.objects.all().order_by("nome")
    )

    return render(
        request,
        "inscricoes/ficha_geral_participante.html",
        {
            "inscricao": inscricao,
            "ministerios": ministerios,  # sÃƒÂ³ serÃƒÂ¡ lista se tipo=servos
            "grupos": grupos,            # agora sempre presente
        },
    )


from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from .models import EventoAcampamento

def evento_configuracoes(request, evento_id):
    # evento_id ÃƒÂ© UUID (vide urls)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    contexto = {
        "evento": evento,
        # links prontos para usar no template
        "url_politica": reverse("inscricoes:editar_politica_reembolso", args=[evento.pk]),
        "url_video": reverse("inscricoes:video_evento_form", kwargs={"slug": evento.slug}),
        "url_participantes": reverse("inscricoes:evento_participantes", args=[evento.pk]),
        "url_admin_paroquia": reverse("inscricoes:admin_paroquia_eventos", args=[evento.paroquia_id]),
    }
    return render(request, "inscricoes/evento_configuracoes.html", contexto)

def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")

import re
from uuid import uuid4, UUID
from decimal import Decimal
from datetime import date, datetime

from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.dateparse import parse_date, parse_datetime

# from .forms import ParticipanteInicialForm, InscricaoCasaisForm
# from .models import (
#     EventoAcampamento, PoliticaPrivacidade, Participante, Inscricao,
#     InscricaoCasais, Filho, Contato
# )

def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

ADDRESS_ALIASES = {
    "cep": ["CEP", "cep", "zip", "postal_code"],
    "endereco": ["endereco", "endereÃƒÂ§o", "address", "rua", "logradouro"],
    "numero": ["numero", "nÃƒÂºmero", "nro", "num"],
    "bairro": ["bairro", "district"],
    "cidade": ["cidade", "city", "municipio", "municÃƒÂ­pio"],
    "estado": ["estado", "uf", "state"],
}

def _extract_address_from_request(request):
    out = {}
    for canonical, variants in ADDRESS_ALIASES.items():
        for name in variants:
            if name in request.POST and request.POST.get(name):
                out[canonical] = request.POST.get(name).strip()
                break
    for k in ["cep","endereco","numero","bairro","cidade","estado"]:
        if k not in out:
            v = request.POST.get(f"addr_{k}") or request.POST.get(f"end_{k}")
            if not v:
                v = request.POST.get(f"endereco[{k}]") or request.POST.get(f"address[{k}]")
            if v:
                out[k] = str(v).strip()
    return out

def _apply_address_to_participante(participante, addr_dict: dict):
    if not addr_dict:
        return
    model_fields_map = {f.name.lower(): f.name for f in participante._meta.get_fields() if hasattr(f, "attname")}
    preferred_keys = {
        "cep": ["CEP", "cep"],
        "endereco": ["endereco", "endereÃƒÂ§o", "logradouro", "rua"],
        "numero": ["numero", "nÃƒÂºmero", "num", "nro"],
        "bairro": ["bairro", "district"],
        "cidade": ["cidade", "city"],
        "estado": ["estado", "uf", "state"],
    }
    to_update = []
    for canonical_key, value in (addr_dict or {}).items():
        if value in (None, ""):
            continue
        candidates = [k.lower() for k in preferred_keys.get(canonical_key, [])] + [canonical_key.lower()]
        real_attr = next((model_fields_map[c] for c in candidates if c in model_fields_map), None)
        if real_attr:
            setattr(participante, real_attr, value)
            to_update.append(real_attr)
    if to_update:
        participante.save(update_fields=to_update)

def _get_optional_post(request, fields):
    data = {}
    for f in fields:
        if f in request.POST:
            val = request.POST.get(f)
            if val is not None and val != "":
                data[f] = val
    return data

def _serialize_value_for_session(v):
    try:
        from django.core.files.uploadedfile import UploadedFile
        if isinstance(v, UploadedFile):
            return None
    except Exception:
        pass
    if hasattr(v, "pk"):
        return v.pk
    if isinstance(v, (list, tuple, set)):
        out = []
        for item in v:
            out.append(item.pk if hasattr(item, "pk") else _serialize_value_for_session(item))
        return out
    try:
        from django.db.models.query import QuerySet
        if isinstance(v, QuerySet):
            return list(v.values_list("pk", flat=True))
    except Exception:
        pass
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    return v

def _serialize_for_session_from_form(form):
    return {k: _serialize_value_for_session(v) for k, v in (form.cleaned_data or {}).items()}

def _deserialize_assign_kwargs(model_cls, data_dict):
    if not data_dict:
        return {}
    from django.db import models as dj_models
    fields = {f.name: f for f in model_cls._meta.get_fields() if hasattr(f, "attname")}
    kwargs = {}

    def _to_bool(val):
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        return s in {"1", "true", "on", "yes", "sim"}

    for k, v in data_dict.items():
        if v in (None, "") or k not in fields:
            continue
        f = fields[k]
        if isinstance(f, (dj_models.ForeignKey, dj_models.OneToOneField)):
            kwargs[f"{k}_id"] = v
            continue
        if isinstance(f, dj_models.DateField) and not isinstance(f, dj_models.DateTimeField):
            if isinstance(v, str):
                dv = parse_date(v)
                if dv is not None:
                    kwargs[k] = dv
                    continue
        if isinstance(f, dj_models.DateTimeField):
            if isinstance(v, str):
                dtv = parse_datetime(v) or parse_datetime(v.replace("Z", "+00:00"))
                if dtv is not None:
                    kwargs[k] = dtv
                    continue
        if isinstance(f, dj_models.DecimalField):
            kwargs[k] = Decimal(str(v)); continue
        if isinstance(f, dj_models.BooleanField):
            kwargs[k] = _to_bool(v); continue
        if isinstance(f, dj_models.IntegerField) and isinstance(v, str) and v.isdigit():
            kwargs[k] = int(v); continue
        kwargs[k] = v
    return kwargs

def _pair_inscricoes(a, b):
    if hasattr(a, "set_pareada"):
        try:
            a.set_pareada(b)
            return
        except Exception:
            pass
    try:
        a.inscricao_pareada = b
        a.save(update_fields=["inscricao_pareada"])
    except Exception:
        pass
    try:
        b.inscricao_pareada = a
        b.save(update_fields=["inscricao_pareada"])
    except Exception:
        pass

def _parse_filhos_from_post(post):
    filhos = []
    try:
        qtd = int(post.get("qtd_filhos") or post.get("id_qtd_filhos") or 0)
    except Exception:
        qtd = 0
    for i in range(1, qtd + 1):
        nome = (post.get(f"filho_{i}_nome") or "").strip()
        idade_raw = (post.get(f"filho_{i}_idade") or "").strip()
        tel  = (post.get(f"filho_{i}_telefone") or "").strip()
        if not (nome or idade_raw or tel):   # ? nada de "ou" em Python
            continue
        try:
            idade = int(idade_raw) if idade_raw else 0
        except Exception:
            idade = 0
        filhos.append({"nome": nome, "idade": idade, "telefone": tel})
    return filhos

# ===================== AJUSTE 1 (helper de salvar arquivo) =====================
def _save_binary_to_filefield(instance, candidate_field_names, filename, data) -> str | None:
    """
    Atribui um ContentFile diretamente ao campo de arquivo (ImageField/CloudinaryField).
    MantÃƒÂ©m a tentativa em mÃƒÂºltiplos nomes de campo e usa savepoints.
    """
    field_names = {f.name for f in instance._meta.get_fields() if hasattr(f, "attname")}
    content = ContentFile(data, name=filename)

    for name in candidate_field_names:
        if name not in field_names:
            continue
        sid = transaction.savepoint()
        try:
            setattr(instance, name, content)
            instance.save(update_fields=[name])
            transaction.savepoint_commit(sid)
            return name
        except Exception:
            transaction.savepoint_rollback(sid)
            continue
    return None
# ==============================================================================

def formulario_casais(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    politica = None
    try:
        politica = PoliticaPrivacidade.objects.first()
    except Exception:
        pass

    etapa = int(request.session.get("casais_etapa", 1))

    form_participante = ParticipanteInicialForm(request.POST or None)
    form_inscricao = InscricaoCasaisForm(request.POST or None, request.FILES or None)

    if hasattr(form_inscricao, "fields") and "foto_casal" in form_inscricao.fields:
        form_inscricao.fields["foto_casal"].required = (etapa == 2)

    # Tudo que mexe em DB fica dentro do atomic:
    if request.method == "POST":
        try:
            with transaction.atomic():
                if etapa == 1:
                    if form_participante.is_valid() and form_inscricao.is_valid():
                        cpf = _digits(form_participante.cleaned_data.get("cpf"))
                        participante1, _ = Participante.objects.update_or_create(
                            cpf=cpf,
                            defaults={
                                "nome": form_participante.cleaned_data.get("nome"),
                                "email": form_participante.cleaned_data.get("email"),
                                "telefone": form_participante.cleaned_data.get("telefone"),
                            }
                        )
                        addr1 = _extract_address_from_request(request)
                        if addr1:
                            _apply_address_to_participante(participante1, addr1)

                        foto_tmp_path = None
                        foto_original_name = None
                        foto_file = form_inscricao.cleaned_data.get("foto_casal")
                        if foto_file:
                            foto_original_name = getattr(foto_file, "name", "foto_casal.jpg")
                            tmp_name = f"tmp/casais/{uuid4()}_{foto_original_name}"
                            foto_tmp_path = default_storage.save(tmp_name, foto_file)

                        dados_insc_serial = _serialize_for_session_from_form(form_inscricao)
                        dados_insc_serial.pop("foto_casal", None)

                        shared_contacts = _get_optional_post(
                            request,
                            [
                                "responsavel_1_nome", "responsavel_1_telefone", "responsavel_1_grau_parentesco", "responsavel_1_ja_e_campista",
                                "responsavel_2_nome", "responsavel_2_telefone", "responsavel_2_grau_parentesco", "responsavel_2_ja_e_campista",
                                "contato_emergencia_nome", "contato_emergencia_telefone", "contato_emergencia_grau_parentesco", "contato_emergencia_ja_e_campista",
                                "tema_acampamento",
                            ]
                        )
                        filhos_serial = _parse_filhos_from_post(request.POST)

                        request.session["conjuge1"] = {
                            "participante_id": participante1.id,
                            "dados_inscricao": dados_insc_serial,
                            "foto_tmp_path": foto_tmp_path,
                            "foto_original_name": foto_original_name,
                            "shared": {
                                "endereco": addr1,
                                "contatos": shared_contacts,
                                "filhos": filhos_serial,
                            }
                        }
                        request.session["casais_etapa"] = 2
                        return redirect("inscricoes:formulario_casais", evento_id=evento.id)

                elif etapa == 2:
                    if form_participante.is_valid() and form_inscricao.is_valid():
                        c1 = request.session.get("conjuge1")
                        if not c1:
                            request.session["casais_etapa"] = 1
                            return redirect("inscricoes:formulario_casais", evento_id=evento.id)

                        participante1 = Participante.objects.get(id=c1["participante_id"])

                        cpf2 = _digits(form_participante.cleaned_data.get("cpf"))
                        participante2, _ = Participante.objects.update_or_create(
                            cpf=cpf2,
                            defaults={
                                "nome": form_participante.cleaned_data.get("nome"),
                                "email": form_participante.cleaned_data.get("email"),
                                "telefone": form_participante.cleaned_data.get("telefone"),
                            }
                        )

                        addr2 = _extract_address_from_request(request) or (c1.get("shared") or {}).get("endereco") or {}
                        if addr2:
                            _apply_address_to_participante(participante1, addr2)
                            _apply_address_to_participante(participante2, addr2)

                        dados1 = _deserialize_assign_kwargs(InscricaoCasais, c1["dados_inscricao"])
                        dados2 = _deserialize_assign_kwargs(InscricaoCasais, _serialize_for_session_from_form(form_inscricao))
                        dados1.pop("foto_casal", None)
                        dados2.pop("foto_casal", None)

                        shared = (c1.get("shared") or {})
                        shared_contacts = (shared.get("contatos") or {})
                        tema_acamp = (shared_contacts.get("tema_acampamento") or "").strip() or None

                        insc1 = Inscricao.objects.create(
                            participante=participante1,   # ? sem espaÃƒÂ§o
                            evento=evento,
                            paroquia=getattr(evento, "paroquia", None),
                            cpf_conjuge=participante2.cpf,
                            **{k: v for k, v in shared_contacts.items() if k != "tema_acampamento"},
                        )
                        insc2 = Inscricao.objects.create(
                            participante=participante2,
                            evento=evento,
                            paroquia=getattr(evento, "paroquia", None),
                            cpf_conjuge=participante1.cpf,
                            **{k: v for k, v in shared_contacts.items() if k != "tema_acampamento"},
                        )

                        if tema_acamp:
                            Inscricao.objects.filter(pk__in=[insc1.pk, insc2.pk]).update(tema_acampamento=tema_acamp)

                        _pair_inscricoes(insc1, insc2)

                        ic1 = InscricaoCasais.objects.create(inscricao=insc1, **dados1)
                        ic2 = InscricaoCasais.objects.create(inscricao=insc2, **dados2)

                        # ===================== AJUSTE 2 (leitura do arquivo) =====================
                        # LÃƒÂª do form_inscricao.files primeiro; se nÃƒÂ£o tiver, cai no request.FILES
                        foto_up = (getattr(form_inscricao, "files", None) or {}).get("foto_casal") \
                                  or request.FILES.get("foto_casal")
                        data = None
                        base_name = "foto_casal.jpg"

                        if foto_up:
                            data = foto_up.read()
                            base_name = getattr(foto_up, "name", base_name)
                        else:
                            tmp_path = (c1 or {}).get("foto_tmp_path")
                            base_name = (c1 or {}).get("foto_original_name") or base_name
                            if tmp_path and default_storage.exists(tmp_path):
                                with default_storage.open(tmp_path, "rb") as fh:
                                    data = fh.read()
                                def _delete_tmp():
                                    try:
                                        default_storage.delete(tmp_path)
                                    except Exception:
                                        pass
                                transaction.on_commit(_delete_tmp)
                        # ==========================================================================

                        if data:
                            def _save_all_images():
                                _save_binary_to_filefield(ic1, ["foto_casal", "foto", "imagem", "image", "photo"], base_name, data)
                                _save_binary_to_filefield(ic2, ["foto_casal", "foto", "imagem", "image", "photo"], base_name, data)
                                _save_binary_to_filefield(participante1, ["foto", "foto_participante", "imagem", "image", "avatar", "photo"], base_name, data)
                                _save_binary_to_filefield(participante2, ["foto", "foto_participante", "imagem", "image", "avatar", "photo"], base_name, data)
                            transaction.on_commit(_save_all_images)

                        filhos = ((c1.get("shared") or {}).get("filhos")) or []
                        for f in filhos:
                            if f.get("nome") or f.get("idade") or f.get("telefone"):
                                Filho.objects.create(inscricao=insc1,nome=f.get("nome", ""),idade=f.get("idade") or 0,telefone=f.get("telefone", ""),)
                                Filho.objects.create(inscricao=insc2,nome=f.get("nome", ""),idade=f.get("idade") or 0,telefone=f.get("telefone", ""),)
                        c_nome = shared_contacts.get("contato_emergencia_nome")
                        c_tel  = shared_contacts.get("contato_emergencia_telefone")
                        c_grau = shared_contacts.get("contato_emergencia_grau_parentesco") or "outro"
                        if c_nome or c_tel:
                            for insc in (insc1, insc2):
                                Contato.objects.create(
                                    inscricao=insc,
                                    nome=c_nome or "",
                                    telefone=c_tel or "",
                                    grau_parentesco=c_grau,
                                    ja_e_campista=False,
                                )

                        request.session.pop("conjuge1", None)
                        request.session.pop("casais_etapa", None)

                        return redirect("inscricoes:ver_inscricao", pk=insc1.id)

        except Exception:
            # Se algo falhar, deixe o Django mostrar a stacktrace em DEBUG
            # (e evita Ã‚â€œtransaÃƒÂ§ÃƒÂ£o quebradaÃ‚â€ continuando a fazer queries)
            raise

    return render(request, "inscricoes/formulario_casais.html", {
        "evento": evento,
        "politica": politica,
        "form": form_participante,
        "form_insc": form_inscricao,
        "etapa": etapa,
    })


# --- helper: resolve o tipo de formulÃƒÂ¡rio efetivo do evento ---
def _tipo_formulario_evento(evento) -> str:
    """
    Retorna o 'tipo efetivo' de formulÃƒÂ¡rio que deve ser usado para o evento.
    Regra: se evento.tipo == 'servos' e estiver vinculado a um evento relacionado
    cujo tipo seja 'casais', o formulÃƒÂ¡rio a usar ÃƒÂ© o de 'casais'.
    Caso contrÃƒÂ¡rio, retorna evento.tipo em minÃƒÂºsculas.
    """
    tipo = (getattr(evento, "tipo", "") or "").lower()
    if tipo == "servos":
        rel = getattr(evento, "evento_relacionado", None)
        if rel and (getattr(rel, "tipo", "") or "").lower() == "casais":
            return "casais"
    return tipo

def _eh_evento_servos(inscricao: Inscricao) -> bool:
    return (getattr(inscricao.evento, "tipo", "") or "").lower() == "servos"



@login_required
@require_POST
def alocar_ministerio(request, inscricao_id: int):
    inscricao = get_object_or_404(
        Inscricao.objects.select_related("evento", "participante", "paroquia"),
        pk=inscricao_id
    )

    if (not request.user.is_superuser
        and getattr(request.user, "paroquia_id", None) != inscricao.evento.paroquia_id):
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    ministerio_id = (request.POST.get("ministerio_id") or "").strip()
    is_coord = (request.POST.get("is_coordenador") or "").lower() in {"1","true","on","yes","sim"}

    # Helper pra voltar para a MESMA pÃƒÂ¡gina
    def back():
        return redirect(request.META.get("HTTP_REFERER") or
                        reverse("inscricoes:ver_inscricao", args=[inscricao.id]))

    # Se veio vazio: remover alocaÃƒÂ§ÃƒÂ£o
    if not ministerio_id:
        qs = AlocacaoMinisterio.objects.filter(inscricao=inscricao, evento=inscricao.evento)
        if qs.exists():
            qs.delete()
            messages.success(request, "Removido(a) do ministÃƒÂ©rio.")
        else:
            messages.info(request, "Este(a) participante nÃƒÂ£o estava em nenhum ministÃƒÂ©rio.")
        return back()

    ministerio = get_object_or_404(Ministerio, pk=ministerio_id)

    aloc, created = AlocacaoMinisterio.objects.get_or_create(
        inscricao=inscricao,
        evento=inscricao.evento,
        defaults={"ministerio": ministerio, "is_coordenador": is_coord},
    )

    if created:
        # Tentar validar (pode falhar na regra de Ã‚â€œum coordenador por ministÃƒÂ©rio/eventoÃ‚â€)
        try:
            aloc.full_clean()
            aloc.save()
            messages.success(request, f"{inscricao.participante.nome} alocado(a) em {ministerio.nome}.")
        except ValidationError as e:
            # Apaga a criaÃƒÂ§ÃƒÂ£o que nÃƒÂ£o passou na validaÃƒÂ§ÃƒÂ£o
            aloc.delete()
            # Pega mensagem amigÃƒÂ¡vel, se existir em is_coordenador
            msg = "; ".join(e.message_dict.get("is_coordenador", e.messages))
            messages.error(request, msg or "NÃƒÂ£o foi possÃƒÂ­vel salvar a alocaÃƒÂ§ÃƒÂ£o.")
        return back()

    # JÃƒÂ¡ havia alocaÃƒÂ§ÃƒÂ£o ? atualizar ministÃƒÂ©rio e/ou coordenaÃƒÂ§ÃƒÂ£o
    antigo = aloc.ministerio.nome
    aloc.ministerio = ministerio
    aloc.is_coordenador = is_coord
    try:
        aloc.full_clean()   # <- onde a sua validaÃƒÂ§ÃƒÂ£o do Ã‚â€œ1 coordenadorÃ‚â€ roda
        aloc.save(update_fields=["ministerio", "is_coordenador"])
        if antigo != ministerio.nome:
            messages.success(request, f"Movido(a) de {antigo} para {ministerio.nome}.")
        else:
            messages.success(request, f"ConfiguraÃƒÂ§ÃƒÂ£o de coordenaÃƒÂ§ÃƒÂ£o atualizada para {ministerio.nome}.")
    except ValidationError as e:
        msg = "; ".join(e.message_dict.get("is_coordenador", e.messages))
        messages.error(request, msg or "NÃƒÂ£o foi possÃƒÂ­vel atualizar a alocaÃƒÂ§ÃƒÂ£o.")
    return back()


@login_required
@require_POST
def alocar_grupo(request, inscricao_id: int):
    insc = get_object_or_404(
        Inscricao.objects.select_related("evento", "paroquia", "participante"),
        pk=inscricao_id
    )
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != insc.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("inscricoes:ver_inscricao", args=[insc.id])

    grupo_raw = (request.POST.get("grupo_id") or "").strip()

    if not grupo_raw:
        deleted, _ = AlocacaoGrupo.objects.filter(inscricao=insc, evento=insc.evento).delete()
        messages.success(request, "AlocaÃƒÂ§ÃƒÂ£o de grupo removida." if deleted else "A inscriÃƒÂ§ÃƒÂ£o nÃƒÂ£o estava alocada a nenhum grupo.")
        return redirect(next_url)

    try:
        grupo_id = int(grupo_raw)
    except ValueError:
        messages.error(request, "Grupo invÃƒÂ¡lido.")
        return redirect(next_url)

    grupo = get_object_or_404(Grupo, pk=grupo_id)

    obj, created = AlocacaoGrupo.objects.update_or_create(
        inscricao=insc, evento=insc.evento, defaults={"grupo": grupo}
    )

    if created:
        messages.success(request, f"{insc.participante.nome} alocado(a) no grupo Ã‚â€œ{grupo.nome}Ã‚â€.")
    else:
        messages.success(request, f"Grupo de {insc.participante.nome} atualizado para Ã‚â€œ{grupo.nome}Ã‚â€.")

    return redirect(next_url)

@login_required
def alocar_em_massa(request: HttpRequest, evento_id: int) -> HttpResponse:
    """
    Tela e aÃƒÂ§ÃƒÂ£o para alocar vÃƒÂ¡rias inscriÃƒÂ§ÃƒÂµes de uma vez em:
      - Grupo (qualquer evento)
      - MinistÃƒÂ©rio (apenas se evento.tipo == 'servos')
    MantÃƒÂ©m o usuÃƒÂ¡rio nesta mesma pÃƒÂ¡gina (PRG: POST -> redirect para a mesma URL).
    """
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    # PermissÃƒÂ£o: admin_geral vÃƒÂª tudo; admin_paroquia apenas a prÃƒÂ³pria parÃƒÂ³quia
    u = request.user
    is_admin_paroquia = _user_is_admin_paroquia(u)
    is_admin_geral = _user_is_admin_geral(u)

    if not (is_admin_paroquia or is_admin_geral):
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")
    if is_admin_paroquia and getattr(u, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o para este evento.")

    # InscriÃƒÂ§ÃƒÂµes deste evento (fonte da grade)
    inscricoes_qs = (
        Inscricao.objects
        .filter(evento=evento)
        .select_related("participante")
        .order_by("participante__nome")
    )

    # CatÃƒÂ¡logos GLOBAIS (NÃƒÆ’O filtrar por evento)
    # Opcional: jÃƒÂ¡ trazendo contagem de alocados no evento para exibir na UI
    ministerios = (
        Ministerio.objects.filter(ativo=True)
        .annotate(alocados_no_evento=Count("alocacoes", filter=Q(alocacoes__evento=evento)))
        .order_by("nome")
    )
    grupos = (
        Grupo.objects.all()
        .annotate(alocados_no_evento=Count("alocacoes", filter=Q(alocacoes__inscricao__evento=evento)))
        .order_by("nome")
    )

    # Filtro por busca de nome/CPF/email (GET ?q=)
    q = (request.GET.get("q") or "").strip()
    if q:
        inscricoes_qs = inscricoes_qs.filter(
            Q(participante__nome__icontains=q)
            | Q(participante__cpf__icontains=q)
            | Q(participante__email__icontains=q)
        )

    total_listados = inscricoes_qs.count()

    if request.method == "POST":
        inscricao_ids = request.POST.getlist("inscricao_ids")  # mÃƒÂºltiplos
        ministerio_id = request.POST.get("ministerio_id") or None
        grupo_id = request.POST.get("grupo_id") or None
        is_coord = (request.POST.get("is_coordenador") == "on")
        funcao_default = (request.POST.get("funcao_default") or "").strip()

        if not inscricao_ids:
            messages.warning(request, "Selecione pelo menos um participante.")
            return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))

        # Apenas inscriÃƒÂ§ÃƒÂµes do prÃƒÂ³prio evento
        alvo_qs = inscricoes_qs.filter(pk__in=inscricao_ids)

        # Valida catÃƒÂ¡logos
        m_obj = None
        g_obj = None

        # MinistÃƒÂ©rio sÃƒÂ³ faz sentido para evento do tipo "Servos"
        if ministerio_id:
            if (evento.tipo or "").lower() != "servos":
                messages.error(request, "Este evento nÃƒÂ£o ÃƒÂ© do tipo Servos Ã‚â€” nÃƒÂ£o ÃƒÂ© possÃƒÂ­vel alocar ministÃƒÂ©rios aqui.")
                return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))
            m_obj = get_object_or_404(Ministerio, pk=ministerio_id)

        if grupo_id:
            g_obj = get_object_or_404(Grupo, pk=grupo_id)

        sucesso_m, sucesso_g, erros = 0, 0, 0

        with transaction.atomic():
            for ins in alvo_qs:
                # ====== MinistÃƒÂ©rio ======
                if m_obj:
                    try:
                        # Um registro por inscriÃƒÂ§ÃƒÂ£o (OneToOne). Se existir, atualiza; senÃƒÂ£o cria.
                        aloc_min, _created = AlocacaoMinisterio.objects.get_or_create(
                            inscricao=ins,
                            defaults={
                                "evento": evento,
                                "ministerio": m_obj,
                                "funcao": (funcao_default or None),
                                "is_coordenador": False,  # decide abaixo
                            },
                        )
                        # Garanta que evento e ministerio sÃƒÂ£o deste contexto
                        aloc_min.evento = evento
                        aloc_min.ministerio = m_obj

                        # Coordenador: permite sÃƒÂ³ 1 por (evento, ministÃƒÂ©rio)
                        if is_coord:
                            existe_coord = (
                                AlocacaoMinisterio.objects
                                .filter(evento=evento, ministerio=m_obj, is_coordenador=True)
                                .exclude(pk=aloc_min.pk)
                                .exists()
                            )
                            if existe_coord:
                                # Mensagem amigÃƒÂ¡vel por pessoa; nÃƒÂ£o interrompe o loop
                                messages.error(
                                    request,
                                    f"{ins.participante.nome}: jÃƒÂ¡ existe um(a) coordenador(a) em Ã‚â€œ{m_obj.nome}Ã‚â€ neste evento. "
                                    "Remova o(a) atual antes de marcar outro(a)."
                                )
                            else:
                                aloc_min.is_coordenador = True
                        else:
                            # Se o checkbox nÃƒÂ£o veio marcado, nÃƒÂ£o mexemos no flag atual (mantÃƒÂ©m o que jÃƒÂ¡ estÃƒÂ¡)
                            pass

                        if funcao_default:
                            aloc_min.funcao = funcao_default

                        aloc_min.full_clean()
                        aloc_min.save()
                        sucesso_m += 1

                    except Exception as e:
                        erros += 1
                        # Evita traceback: registra mensagem e segue
                        messages.error(request, f"{ins.participante.nome}: nÃƒÂ£o foi possÃƒÂ­vel alocar no ministÃƒÂ©rio ({e}).")

                # ====== Grupo ======
                if g_obj:
                    try:
                        ag, _ = AlocacaoGrupo.objects.get_or_create(
                            inscricao=ins,
                            defaults={"grupo": g_obj},
                        )
                        ag.grupo = g_obj
                        ag.full_clean()
                        ag.save()
                        sucesso_g += 1
                    except Exception as e:
                        erros += 1
                        messages.error(request, f"{ins.participante.nome}: nÃƒÂ£o foi possÃƒÂ­vel alocar no grupo ({e}).")

        # Feedback acumulado
        if sucesso_m:
            messages.success(request, f"{sucesso_m} participante(s) alocado(s) ao ministÃƒÂ©rio {m_obj.nome}.")
            if is_coord:
                messages.info(request, "Tentativa de marcar como coordenador(a) aplicada onde possÃƒÂ­vel.")
            if funcao_default:
                messages.info(request, f"FunÃƒÂ§ÃƒÂ£o aplicada: Ã‚â€œ{funcao_default}Ã‚â€.")
        if sucesso_g:
            messages.success(request, f"{sucesso_g} participante(s) alocado(s) ao grupo {g_obj.nome}.")
        if erros:
            messages.error(request, f"{erros} registro(s) tiveram erro. Revise as mensagens acima.")

        # PRG: volta para a mesma pÃƒÂ¡gina
        return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))

    # GET: renderiza pÃƒÂ¡gina
    return render(
        request,
        "inscricoes/alocar_em_massa.html",
        {
            "evento": evento,
            "inscricoes": inscricoes_qs,
            "total_listados": total_listados,
            "grupos": grupos,
            "ministerios": ministerios,
            "pode_ministerio": (evento.tipo or "").lower() == "servos",
        },
    )


@login_required
def ministerios_evento(request, evento_id):
    evento = get_object_or_404(
        EventoAcampamento.objects.select_related("paroquia"), pk=evento_id
    )

    if not _can_manage_event(request.user, evento):
        return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para gerenciar este evento.")

    if (evento.tipo or "").lower() != "servos":
        messages.warning(request, "MinistÃƒÂ©rios sÃƒÂ³ se aplicam a eventos do tipo Servos.")
        ministerios = Ministerio.objects.none()
    else:
        ministerios = (
            Ministerio.objects
            .filter(evento=evento)
            .annotate(
                total_servos=Count("alocacoes", filter=Q(alocacoes__ministerio__isnull=False)),
                total_coord=Count("alocacoes", filter=Q(alocacoes__is_coordenador=True)),
            )
            .order_by("nome")
        )

    if request.method == "POST":
        nome = (request.POST.get("nome") or "").strip()
        descricao = (request.POST.get("descricao") or "").strip() or None

        if not nome:
            messages.error(request, "Informe o nome do ministÃƒÂ©rio.")
        else:
            m = Ministerio(evento=evento, nome=nome, descricao=descricao)
            try:
                m.full_clean()
                m.save()
                messages.success(request, f"MinistÃƒÂ©rio Ã‚â€œ{m.nome}Ã‚â€ criado com sucesso.")
                return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))
            except ValidationError as e:
                for errs in e.message_dict.values():
                    for err in errs:
                        messages.error(request, err)

    return render(
        request,
        "inscricoes/ministerios_evento.html",
        {
            "evento": evento,
            "ministerios": ministerios,
            "pode_cadastrar": (evento.tipo or "").lower() == "servos",
        },
    )


@login_required
def excluir_ministerio(request, pk: int):
    """Exclui um ministÃƒÂ©rio (se nÃƒÂ£o tiver alocaÃƒÂ§ÃƒÂµes)."""
    ministerio = get_object_or_404(
        Ministerio.objects.select_related("evento__paroquia"),
        pk=pk
    )
    evento = ministerio.evento

    if not _can_manage_event(request.user, evento):
        return HttpResponseForbidden("VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para esta aÃƒÂ§ÃƒÂ£o.")

    if request.method != "POST":
        return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))

    # ?? Trocar inscricoes ? alocacoes
    if ministerio.alocacoes.exists():
        messages.error(request, "NÃƒÂ£o ÃƒÂ© possÃƒÂ­vel excluir: hÃƒÂ¡ servos alocados neste ministÃƒÂ©rio.")
        return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))

    nome = ministerio.nome
    ministerio.delete()
    messages.success(request, f"MinistÃƒÂ©rio Ã‚â€œ{nome}Ã‚â€ excluÃƒÂ­do com sucesso.")
    return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))


@login_required
def ministerios_home(request, paroquia_id: int):
    """
    Home dos ministÃƒÂ©rios por parÃƒÂ³quia:
    - Lista todos os eventos da parÃƒÂ³quia (destaque para 'Servos').
    - BotÃƒÂ£o para abrir ministÃƒÂ©rios SEMPRE visÃƒÂ­vel.
    """
    user = request.user
    is_admin_paroquia = _is_admin_paroquia(user)
    is_admin_geral = _is_admin_geral(user)

    if is_admin_paroquia and getattr(user, "paroquia_id", None) != paroquia_id and not is_admin_geral:
        messages.error(request, "VocÃƒÂª nÃƒÂ£o pode acessar os ministÃƒÂ©rios de outra parÃƒÂ³quia.")
        return redirect("inscricoes:admin_paroquia_painel")

    paroquia = get_object_or_404(Paroquia, id=paroquia_id)

    qs = EventoAcampamento.objects.filter(paroquia=paroquia)
    eventos = None
    for ordering in [("-data_inicio", "-created_at"), ("-data_inicio",), ("-created_at",), ("-pk",)]:
        try:
            eventos = qs.order_by(*ordering)
            break
        except FieldError:
            continue
    if eventos is None:
        eventos = qs

    eventos_servos = list(eventos.filter(tipo__iexact="servos"))
    outros_eventos = list(eventos.exclude(tipo__iexact="servos"))

    return render(
        request,
        "inscricoes/ministerios_home.html",
        {
            "paroquia": paroquia,
            "eventos_servos": eventos_servos,
            "outros_eventos": outros_eventos,
            "is_admin_paroquia": is_admin_paroquia,
            "is_admin_geral": is_admin_geral,
        },
    )

@login_required
def ministerio_create(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    if not _check_perm_evento(request.user, evento):
        return HttpResponseForbidden("Sem permissÃƒÂ£o para este evento.")

    if (evento.tipo or "").lower() != "servos":
        messages.error(request, "MinistÃƒÂ©rios sÃƒÂ³ sÃƒÂ£o permitidos para eventos do tipo Servos.")
        return redirect("inscricoes:ministerios_evento", evento.id)

    if request.method == "POST":
        form = MinisterioForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.evento = evento
            obj.full_clean()
            obj.save()
            messages.success(request, "MinistÃƒÂ©rio cadastrado com sucesso.")
            return redirect("inscricoes:ministerios_evento", evento.id)
    else:
        form = MinisterioForm()

    return render(request, "inscricoes/ministerio_form.html", {
        "evento": evento,
        "form": form,
    })

@login_required
def admin_paroquia_acoes(request, paroquia_id: Optional[int] = None):
    """
    PÃƒÂ¡gina de AÃƒÂ§ÃƒÂµes & ConfiguraÃƒÂ§ÃƒÂµes da parÃƒÂ³quia:
    - Admin da parÃƒÂ³quia: usa a parÃƒÂ³quia vinculada ao usuÃƒÂ¡rio.
    - Admin geral: precisa informar paroquia_id (ex.: /admin-paroquia/acoes/3/).
    """
    user = request.user

    # Detecta papÃƒÂ©is (mesma lÃƒÂ³gica do seu painel)
    if hasattr(user, "is_admin_paroquia") and callable(user.is_admin_paroquia):
        is_admin_paroquia = bool(user.is_admin_paroquia())
    else:
        is_admin_paroquia = getattr(user, "tipo_usuario", "") == "admin_paroquia"

    if hasattr(user, "is_admin_geral") and callable(user.is_admin_geral):
        is_admin_geral = bool(user.is_admin_geral())
    else:
        is_admin_geral = bool(getattr(user, "is_superuser", False)) or (
            getattr(user, "tipo_usuario", "") == "admin_geral"
        )

    # SeleÃƒÂ§ÃƒÂ£o da parÃƒÂ³quia conforme papel
    if is_admin_paroquia:
        paroquia = getattr(user, "paroquia", None)
        if not paroquia:
            messages.error(request, "?? Sua conta nÃƒÂ£o estÃƒÂ¡ vinculada a uma parÃƒÂ³quia.")
            return redirect("inscricoes:logout")

        # se tentarem acessar outra parÃƒÂ³quia via URL, redireciona para a correta
        if paroquia_id and int(paroquia_id) != getattr(user, "paroquia_id", None):
            return redirect(reverse("inscricoes:admin_paroquia_acoes"))
    elif is_admin_geral:
        if not paroquia_id:
            messages.error(request, "?? ParÃƒÂ³quia nÃƒÂ£o especificada.")
            return redirect("inscricoes:admin_geral_list_paroquias")
        paroquia = get_object_or_404(Paroquia, id=paroquia_id)
    else:
        messages.error(request, "?? VocÃƒÂª nÃƒÂ£o tem permissÃƒÂ£o para acessar esta pÃƒÂ¡gina.")
        return redirect("inscricoes:logout")

    return render(
        request,
        "inscricoes/admin_paroquia_acoes.html",
        {
            "paroquia": paroquia,
            "is_admin_paroquia": is_admin_paroquia,
            "is_admin_geral": is_admin_geral,
            # pode passar outros dados se quiser exibir contagens/resumos
        },
    )

def _can_manage_event(user, evento) -> bool:
    # mesma regra que vocÃƒÂª jÃƒÂ¡ usa em outras views
    if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
        return True
    return getattr(user, "tipo_usuario", "") == "admin_paroquia" and getattr(user, "paroquia_id", None) == getattr(evento, "paroquia_id", None)

# ==============================================================
# Aliases amigÃƒÂ¡veis de status (front pode mandar "pago", etc.)
# ==============================================================
STATUS_ALIASES = {
    "pago": InscricaoStatus.PAG_CONFIRMADO,
    "pagamento_confirmado": InscricaoStatus.PAG_CONFIRMADO,
    "pendente": InscricaoStatus.PAG_PENDENTE,
    "selecionado": InscricaoStatus.CONVOCADA,
    "selecionada": InscricaoStatus.CONVOCADA,
    "aprovado": InscricaoStatus.APROVADA,
    "aprovada": InscricaoStatus.APROVADA,
    "analise": InscricaoStatus.EM_ANALISE,
    "em_analise": InscricaoStatus.EM_ANALISE,
    "rejeitado": InscricaoStatus.REJEITADA,
    "rejeitada": InscricaoStatus.REJEITADA,
    "espera": InscricaoStatus.LISTA_ESPERA,
    "lista_espera": InscricaoStatus.LISTA_ESPERA,
}

# ==============================================================
# POST /inscricao/<id>/alterar-status/
# ==============================================================
@login_required
@require_POST
def alterar_status_inscricao(request, inscricao_id: int):
    """
    Recebe 'status' (form-urlencoded ou JSON),
    aceita aliases e aplica Inscricao.mudar_status(...).
    Retorna JSON com flags para atualizar a UI.
    """
    try:
        insc = (
            Inscricao.objects.select_related("paroquia", "evento", "participante")
            .get(pk=inscricao_id)
        )
    except Inscricao.DoesNotExist:
        return HttpResponseBadRequest("InscriÃƒÂ§ÃƒÂ£o nÃƒÂ£o encontrada")

    # ===== PermissÃƒÂ£o =====
    u = request.user
    is_admin_geral = False
    is_admin_paroquia = False
    try:
        is_admin_geral = bool(u.is_admin_geral())
    except Exception:
        is_admin_geral = bool(getattr(u, "is_superuser", False)) or (
            getattr(u, "tipo_usuario", "") == "admin_geral"
        )
    try:
        is_admin_paroquia = bool(u.is_admin_paroquia())
    except Exception:
        is_admin_paroquia = (getattr(u, "tipo_usuario", "") == "admin_paroquia")

    if not (is_admin_geral or (is_admin_paroquia and u.paroquia_id == insc.paroquia_id)):
        return JsonResponse({"ok": False, "error": "Acesso negado."}, status=403)

    # ===== Body robusto =====
    payload = {}
    ctype = (request.content_type or "").lower()
    if ctype.startswith("application/json"):
        try:
            payload = json.loads((request.body or b"").decode("utf-8") or "{}")
        except Exception:
            payload = {}
    else:
        # aceita form-urlencoded normal ou manual
        if request.POST:
            payload = request.POST
        else:
            # fallback pra casos que mandam raw form-urlencoded
            try:
                payload = {k: v[0] for k, v in parse_qs((request.body or b"").decode("utf-8")).items()}
            except Exception:
                payload = {}

    new_status = (payload.get("status") or "").strip()
    if not new_status:
        return JsonResponse(
            {
                "ok": False,
                "error": "Campo 'status' ausente.",
                "validos": sorted({c for c, _ in InscricaoStatus.choices}),
            },
            status=400,
        )

    # normaliza e resolve aliases
    new_status_norm = new_status.lower()
    if new_status_norm in STATUS_ALIASES:
        new_status = STATUS_ALIASES[new_status_norm]

    # valida cÃƒÂ³digo final
    codigos_validos = {c for c, _ in InscricaoStatus.choices}
    if new_status not in codigos_validos:
        return JsonResponse(
            {
                "ok": False,
                "error": "Status invÃƒÂ¡lido.",
                "recebido": new_status,
                "validos": sorted(codigos_validos),
            },
            status=400,
        )

    # aplica transiÃƒÂ§ÃƒÂ£o
    try:
        insc.mudar_status(new_status, motivo="Painel participantes", por_usuario=u)
    except Exception as e:
        # inclui a mensagem do ValidationError, se houver
        msg = getattr(e, "message", None) or getattr(e, "messages", [None])[0] or "Falha ao salvar."
        return JsonResponse({"ok": False, "error": msg}, status=400)

    return JsonResponse(
        {
            "ok": True,
            "id": insc.pk,
            "status": insc.status,
            "label": insc.get_status_display(),
            "foi_selecionado": insc.foi_selecionado,
            "pagamento_confirmado": insc.pagamento_confirmado,
        }
    )


# ==============================================================
# GET /admin-paroquia/evento/<evento_id>/participantes/
# ==============================================================
# inscricoes/views.py  (trecho relevante)

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from inscricoes.models import (
    EventoAcampamento,
    Inscricao,
    InscricaoStatus,
)

@login_required
def evento_participantes(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # -------- Permissões --------
    u = request.user
    try:
        is_admin_paroquia = bool(u.is_admin_paroquia())
    except Exception:
        is_admin_paroquia = (getattr(u, "tipo_usuario", "") == "admin_paroquia")

    try:
        is_admin_geral = bool(u.is_admin_geral())
    except Exception:
        is_admin_geral = bool(getattr(u, "is_superuser", False)) or (
            getattr(u, "tipo_usuario", "") == "admin_geral"
        )

    if is_admin_paroquia:
        if getattr(u, "paroquia_id", None) != getattr(evento, "paroquia_id", None):
            return HttpResponseForbidden("Acesso negado.")
    elif not is_admin_geral:
        return HttpResponseForbidden("Acesso negado.")

    # -------- Query base --------
    inscricoes = (
        Inscricao.objects.filter(evento=evento)
        .select_related(
            "participante", "evento", "paroquia",
            "inscricaosenior", "inscricaojuvenil", "inscricaomirim",
            "inscricaoservos", "inscricaocasais", "inscricaoevento", "inscricaoretiro",
        )
        .prefetch_related("alocacao_grupo__grupo", "alocacao_ministerio__ministerio")
        .order_by("participante__nome")
    )

    # -------- Idade --------
    ref_date = getattr(evento, "data_inicio", None) or timezone.localdate()
    attr_by_tipo = {
        "senior": "inscricaosenior",
        "juvenil": "inscricaojuvenil",
        "mirim": "inscricaomirim",
        "servos": "inscricaoservos",
        "casais": "inscricaocasais",
        "evento": "inscricaoevento",
        "retiro": "inscricaoretiro",
    }

    def _calc_age(nasc, ref):
        if not nasc:
            return None
        if hasattr(nasc, "date"):
            nasc = nasc.date()
        if hasattr(ref, "date"):
            ref = ref.date()
        return ref.year - nasc.year - ((ref.month, ref.day) < (nasc.month, nasc.day))

    def _get_birth(insc: "Inscricao"):
        """Procura data de nascimento nas bases relacionadas; se não achar, cai no participante."""
        tipo = (getattr(insc.evento, "tipo", "") or "").lower()
        ordem = []
        pref = attr_by_tipo.get(tipo)
        if pref:
            ordem.append(pref)
        ordem += [
            "inscricaosenior", "inscricaojuvenil", "inscricaomirim",
            "inscricaoservos", "inscricaocasais", "inscricaoevento", "inscricaoretiro",
        ]
        vistos = set()
        for name in [n for n in ordem if n and n not in vistos]:
            vistos.add(name)
            rel = getattr(insc, name, None)
            if rel:
                dn = getattr(rel, "data_nascimento", None)
                if dn:
                    return dn
        return getattr(insc.participante, "data_nascimento", None)

    def _ensure_idade(obj: "Inscricao|None"):
        if obj is None:
            return
        if getattr(obj, "idade", None) is None:
            obj.idade = _calc_age(_get_birth(obj), ref_date)

    for insc in inscricoes:
        _ensure_idade(insc)

    # -------- Helpers de pareamento --------
    def _par_de(insc: "Inscricao"):
        """Tenta localizar o par dentro do mesmo evento por múltiplas convenções."""
        try:
            p = insc.par
            if p:
                return p
        except Exception:
            pass
        if getattr(insc, "inscricao_pareada_id", None):
            return getattr(insc, "inscricao_pareada", None)
        return getattr(insc, "pareada_por", None)

    # -------- Flags do tipo de evento --------
    tipo_evento = (getattr(evento, "tipo", "") or "").lower()
    rel = getattr(evento, "evento_relacionado", None)
    tipo_rel = (getattr(rel, "tipo", "") or "").lower() if rel else ""
    is_evento_casais = (tipo_evento == "casais")
    is_servos_de_casal = (tipo_evento == "servos" and rel and tipo_rel == "casais")

    # ======================================================================
    # Pareamento + Dedup (linhas a exibir)
    # ======================================================================
    linhas = []

    if is_evento_casais:
        for insc in inscricoes:
            par = _par_de(insc)
            # evita duplicar (mantém o de menor id)
            if par and getattr(par, "id", None) and insc.id and not (insc.id < par.id):
                continue
            setattr(insc, "par_inscrito", par if par else None)
            linhas.append(insc)

    elif is_servos_de_casal:
        par_map = {}
        if rel:
            casal_qs = (
                Inscricao.objects.filter(evento=rel)
                .select_related("participante")
                .only("id", "participante_id", "inscricao_pareada_id")
            )
            for insc_casal in casal_qs:
                par = _par_de(insc_casal)
                if par:
                    a = getattr(insc_casal, "participante_id", None)
                    b = getattr(par, "participante_id", None)
                    if a and b:
                        par_map[a] = b
                        par_map[b] = a

        def _partner_pid_from_participant(participante):
            for attr in ("conjuge_id", "parceiro_id", "spouse_id", "par_id", "conjugue_id", "conjuge__id"):
                pid = getattr(participante, attr, None)
                if pid:
                    return pid
            for obj_attr in ("conjuge", "parceiro", "spouse", "par"):
                obj = getattr(participante, obj_attr, None)
                pid = getattr(obj, "id", None)
                if pid:
                    return pid
            return None

        servos_by_part = {i.participante_id: i for i in inscricoes}

        def _find_partner_inscricao(insc: "Inscricao"):
            pid = getattr(insc, "participante_id", None)
            if not pid:
                return None

            pid_par = par_map.get(pid)
            if pid_par:
                insc_par = servos_by_part.get(pid_par)
                if insc_par:
                    return insc_par

            participante = getattr(insc, "participante", None)
            if participante:
                pid_par_b = _partner_pid_from_participant(participante)
                if pid_par_b:
                    insc_par_b = servos_by_part.get(pid_par_b)
                    if insc_par_b:
                        return insc_par_b

            par_local = _par_de(insc)
            if par_local:
                return par_local
            return None

        vistos = set()
        for insc in inscricoes:
            if insc.id in vistos:
                continue
            par_insc = _find_partner_inscricao(insc)
            if par_insc:
                vistos.add(getattr(par_insc, "id", None))
                a = getattr(insc, "participante_id", 0) or 0
                b = getattr(par_insc, "participante_id", 0) or 0
                keep = insc
                drop = par_insc
                if a and b and b < a:
                    keep, drop = par_insc, insc
                elif (not a or not b) and getattr(par_insc, "id", 0) < getattr(insc, "id", 0):
                    keep, drop = par_insc, insc
                setattr(keep, "par_inscrito", drop)
                linhas.append(keep)
            else:
                setattr(insc, "par_inscrito", None)
                linhas.append(insc)

    else:
        for insc in inscricoes:
            setattr(insc, "par_inscrito", None)
            linhas.append(insc)

    # Garante idade no par também
    for row in linhas:
        _ensure_idade(row)
        for candidate in (
            getattr(row, "par_inscrito", None),
            getattr(row, "par", None),
            getattr(row, "inscricao_casal", None),
            getattr(row, "casal_vinculado", None),
        ):
            _ensure_idade(candidate)

    # ======================================================================
    # Contadores (Participantes = pessoas / Casais = pares)
    # ======================================================================
    base_qs = Inscricao.objects.filter(evento=evento)

    # >>> Participantes = total de PESSOAS/inscrições (sem dedupe)
    total_participantes = base_qs.count()

    # Seleção por pessoa
    total_selecionados = base_qs.filter(foi_selecionado=True).count()
    total_pendentes   = base_qs.filter(foi_selecionado=False).count()

    # Confirmados por status
    total_confirmados = base_qs.filter(status=InscricaoStatus.PAG_CONFIRMADO).count()

    # KPIs de Casais
    total_casais = total_casais_confirmados = total_casais_selecionados = total_casais_pendentes = 0
    if is_evento_casais or is_servos_de_casal:
        for row in linhas:
            par = getattr(row, "par_inscrito", None) or _par_de(row)
            if not par:
                continue  # sem par => não conta casal

            total_casais += 1

            # Confirmados: ambos com pagamento confirmado
            if (getattr(row, "status", None) == InscricaoStatus.PAG_CONFIRMADO and
                getattr(par,  "status", None) == InscricaoStatus.PAG_CONFIRMADO):
                total_casais_confirmados += 1

            # Selecionados: ambos com foi_selecionado=True
            a_sel = bool(getattr(row, "foi_selecionado", False))
            b_sel = bool(getattr(par,  "foi_selecionado", False))
            if a_sel and b_sel:
                total_casais_selecionados += 1

            # Pendentes: pelo menos um não selecionado
            if not (a_sel and b_sel):
                total_casais_pendentes += 1

    # -------- Contexto --------
    context = {
        "evento": evento,
        "participantes": linhas,  # já deduplicado; cada row pode ter .par_inscrito
        "is_evento_casais": is_evento_casais,
        "is_servos_de_casal": is_servos_de_casal,
        "valor_inscricao": getattr(evento, "valor_inscricao", None),

        # KPIs gerais (pessoas)
        "total_participantes": total_participantes,  # << pessoas (inscrições)
        "total_confirmados": total_confirmados,
        "total_selecionados": total_selecionados,
        "total_pendentes": total_pendentes,

        # KPIs de casais (pares)
        "total_casais": total_casais,
        "total_casais_confirmados": total_casais_confirmados,
        "total_casais_selecionados": total_casais_selecionados,
        "total_casais_pendentes": total_casais_pendentes,

        "status_choices": InscricaoStatus.choices,
    }
    return render(request, "inscricoes/evento_participantes.html", context)


from .forms import MinisterioForm

@require_http_methods(["GET", "POST"])
@login_required
def ministerio_novo(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if (evento.tipo or "").lower() != "servos":
        messages.error(request, "MinistÃƒÂ©rios sÃƒÂ³ fazem sentido em eventos do tipo Servos.")
        return redirect("inscricoes:ministerios_evento", evento_id=evento.id)

    # PermissÃƒÂ£o
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    if request.method == "POST":
        form = MinisterioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "MinistÃƒÂ©rio criado no catÃƒÂ¡logo global.")
            return redirect("inscricoes:ministerios_evento", evento_id=evento.id)
    else:
        form = MinisterioForm()

    return render(request, "inscricoes/ministerio_novo.html", {
        "evento": evento,
        "form": form,
    })


from django.forms import modelform_factory

@login_required
@require_http_methods(["GET", "POST"])
def ministerio_editar(request, pk: int):
    ministerio = get_object_or_404(Ministerio, pk=pk)

    # Por ser GLOBAL, recomendo restringir a superuser.
    if not request.user.is_superuser:
        return HttpResponseForbidden("EdiÃƒÂ§ÃƒÂ£o do catÃƒÂ¡logo global restrita ao administrador geral.")

    if request.method == "POST":
        form = MinisterioForm(request.POST, instance=ministerio)
        if form.is_valid():
            form.save()
            messages.success(request, "MinistÃƒÂ©rio atualizado com sucesso.")
            # Volta para a listagem geral de ministÃƒÂ©rios do sistema
            return redirect(reverse("inscricoes:ministerios_evento", args=[request.GET.get("evento")]) if request.GET.get("evento") else "/admin/")
    else:
        form = MinisterioForm(instance=ministerio)

    return render(request, "inscricoes/ministerio_form.html", {
        "form": form,
        "ministerio": ministerio,
    })


from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.http import HttpResponseForbidden

@login_required
def alocacoes_ministerio(request, pk: int, evento_id):
    """
    Lista alocados de um ministÃƒÂ©rio *neste evento* e mostra o form para incluir mais.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    alocados = (
        AlocacaoMinisterio.objects
        .filter(evento=evento, ministerio=ministerio)
        .select_related("inscricao__participante")
        .order_by("-is_coordenador", "inscricao__participante__nome")
    )

    # >>> PASSAR evento e ministerio evita o KeyError
    form = AlocarInscricaoForm(request.POST or None, evento=evento, ministerio=ministerio)

    if request.method == "POST" and form.is_valid():
        insc = form.cleaned_data["inscricao"]
        try:
            AlocacaoMinisterio.objects.create(
                inscricao=insc,
                evento=evento,
                ministerio=ministerio,
            )
            messages.success(request, f"{insc.participante.nome} alocado(a) em {ministerio.nome}.")
            return redirect(reverse("inscricoes:alocacoes_ministerio", args=[ministerio.id, evento.id]))
        except Exception as e:
            messages.error(request, str(e))

    return render(request, "inscricoes/alocacoes_ministerio.html", {
        "evento": evento,
        "ministerio": ministerio,
        "alocados": alocados,
        "form": form,
    })


@login_required
@require_POST
def alocar_inscricao_ministerio(request, pk: int, evento_id):
    """
    Handler do POST de alocaÃƒÂ§ÃƒÂ£o via botÃƒÂ£o/linha separada.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    # >>> PASSAR evento e ministerio evita o KeyError
    form = AlocarInscricaoForm(request.POST, evento=evento, ministerio=ministerio)
    if form.is_valid():
        insc = form.cleaned_data["inscricao"]
        try:
            AlocacaoMinisterio.objects.create(
                inscricao=insc,
                evento=evento,
                ministerio=ministerio,
            )
            messages.success(request, f"{insc.participante.nome} alocado(a) em {ministerio.nome}.")
        except Exception as e:
            messages.error(request, str(e))
    else:
        for _, errs in form.errors.items():
            for err in errs:
                messages.error(request, err)

    return redirect(reverse("inscricoes:alocacoes_ministerio", args=[ministerio.id, evento.id]))


@login_required
@require_POST
def desalocar_inscricao_ministerio(request, alocacao_id: int):
    aloc = get_object_or_404(
        AlocacaoMinisterio.objects.select_related("inscricao__participante", "evento"),
        pk=alocacao_id
    )
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != aloc.evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    nome = aloc.inscricao.participante.nome
    mid = aloc.ministerio_id
    eid = aloc.evento_id
    aloc.delete()
    messages.success(request, f"{nome} removido(a) do ministÃƒÂ©rio.")
    return redirect(reverse("inscricoes:alocacoes_ministerio", args=[mid, eid]))

@login_required
@require_POST
def toggle_coordenador_ministerio(request, alocacao_id: int):
    aloc = get_object_or_404(
        AlocacaoMinisterio.objects.select_related("evento", "inscricao__participante"),
        pk=alocacao_id
    )
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != aloc.evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    ativo = (request.POST.get("ativo") or "").strip().lower() in {"1","true","on","yes","sim"}
    aloc.is_coordenador = ativo
    try:
        aloc.full_clean()
        aloc.save(update_fields=["is_coordenador"])
        msg = "marcado(a) como coordenador(a)." if ativo else "removido(a) da coordenaÃƒÂ§ÃƒÂ£o."
        messages.success(request, f"{aloc.inscricao.participante.nome} {msg}")
    except Exception as e:
        messages.error(request, str(e))

    return redirect(reverse("inscricoes:alocacoes_ministerio", args=[aloc.ministerio_id, aloc.evento_id]))

@login_required
def ministerios_evento(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    # PermissÃƒÂ£o bÃƒÂ¡sica
    if (not request.user.is_superuser
        and getattr(request.user, "paroquia_id", None) != evento.paroquia_id):
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    # IMPORTANTÃƒÂSSIMO: o related_name abaixo precisa existir no model de AlocacaoMinisterio
    # class AlocacaoMinisterio(models.Model):
    #     ministerio = models.ForeignKey(Ministerio, related_name="alocacoes", ...)
    #     evento = models.ForeignKey(EventoAcampamento, ...)
    #
    # Se o seu related_name nÃƒÂ£o for "alocacoes", ajuste as 2 linhas com "alocacoes" aqui.

    # PrÃƒÂ©-busca: todas as alocaÃƒÂ§ÃƒÂµes deste evento (para montar a lista e tambÃƒÂ©m contagens fallback)
    alocs_qs = (
        AlocacaoMinisterio.objects
        .filter(evento=evento)
        .select_related("inscricao__participante")  # ÃƒÂºtil para telas de detalhes
        .order_by()  # evita ORDER BY desnecessÃƒÂ¡rio que pode afetar o COUNT DISTINCT
    )

    # Query principal dos ministÃƒÂ©rios
    ministerios_qs = (
        Ministerio.objects.filter(ativo=True)
        .annotate(
            # DISTINCT evita duplicidades de joins (seguro)
            alocacoes_count=Count("alocacoes", filter=Q(alocacoes__evento=evento), distinct=True)
        )
        .prefetch_related(
            Prefetch("alocacoes", queryset=alocs_qs, to_attr="alocacoes_do_evento")
        )
        .order_by("nome")
    )

    # Convertemos em lista para poder somar e reutilizar sem repetir queries
    ministerios = list(ministerios_qs)

    # Totais prontos para o template
    total_ministerios = len(ministerios)
    # Se vocÃƒÂª quer o total geral de pessoas alocadas no evento (soma de todos os ministÃƒÂ©rios):
    total_alocados = sum(len(m.alocacoes_do_evento) for m in ministerios)

    return render(request, "inscricoes/ministerios_evento.html", {
        "evento": evento,
        "ministerios": ministerios,
        "total_ministerios": total_ministerios,
        "total_alocados": total_alocados,
    })

@login_required
@require_POST
def ministerio_deletar(request, pk: int):
    """
    Deleta um MinistÃƒÂ©rio (catÃƒÂ¡logo global) **apenas** se nÃƒÂ£o houver alocaÃƒÂ§ÃƒÂµes.
    Se vier evento_id (via POST/GET), usamos para voltar ÃƒÂ  tela do evento.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)

    # PermissÃƒÂ£o: superuser ou admin da mesma parÃƒÂ³quia de um evento alvo (quando informado)
    evento_id = request.POST.get("evento_id") or request.GET.get("evento_id")
    evento = None
    if evento_id:
        try:
            evento = EventoAcampamento.objects.get(pk=evento_id)
        except EventoAcampamento.DoesNotExist:
            evento = None

    # Regra simples: se nÃƒÂ£o for superuser e houver evento no contexto, sÃƒÂ³ permite se for a mesma parÃƒÂ³quia
    if not request.user.is_superuser and evento and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissÃƒÂ£o.")

    # Bloqueia exclusÃƒÂ£o se houver qualquer alocaÃƒÂ§ÃƒÂ£o (em qualquer evento)
    if ministerio.alocacoes.exists():
        messages.error(request, "NÃƒÂ£o ÃƒÂ© possÃƒÂ­vel excluir: existem participantes alocados neste ministÃƒÂ©rio.")
        if evento:
            return redirect("inscricoes:ministerios_evento", evento_id=evento.id)
        return redirect("inscricoes:ministerios_home_sem_paroquia")

    nome = ministerio.nome
    ministerio.delete()
    messages.success(request, f"MinistÃƒÂ©rio Ã‚â€œ{nome}Ã‚â€ excluÃƒÂ­do com sucesso.")
    if evento:
        return redirect("inscricoes:ministerios_evento", evento_id=evento.id)
    return redirect("inscricoes:ministerios_home_sem_paroquia")

@login_required
def alocacoes_ministerio_short(request, pk: int):
    """
    Compat: usuÃƒÂ¡rio caiu na rota sem evento_id.
    Tentamos descobrir o ÃƒÂºltimo evento onde esse ministÃƒÂ©rio tem alocaÃƒÂ§ÃƒÂ£o
    e redirecionamos para a rota correta. Se nÃƒÂ£o houver, mandamos para a home.
    """
    ultima = (
        AlocacaoMinisterio.objects
        .filter(ministerio_id=pk)
        .select_related("evento")
        .order_by("-data_alocacao")
        .first()
    )
    if ultima and ultima.evento_id:
        return redirect("inscricoes:alocacoes_ministerio",
                        pk=pk, evento_id=ultima.evento_id)

    messages.warning(request, "Escolha o evento para esse ministÃƒÂ©rio.")
    return redirect("inscricoes:ministerios_home_sem_paroquia")

from django.db import transaction

def _par_de(insc: Inscricao):
    """Tenta achar a inscriÃƒÂ§ÃƒÂ£o pareada (par) para eventos de casais."""
    # 1) property par (se existir no seu modelo)
    try:
        p = insc.par
        if p:
            return p
    except Exception:
        pass
    # 2) campo direto
    if getattr(insc, "inscricao_pareada_id", None):
        return getattr(insc, "inscricao_pareada", None)
    # 3) reverse comum (se existir)
    return getattr(insc, "pareada_por", None)

def _find_pair_in_same_event(insc: Inscricao):
    """
    Retorna a inscriÃƒÂ§ÃƒÂ£o do PAR dentro do MESMO evento, cobrindo:
      - Evento de CASAIS: usa o pareamento direto (par, inscricao_pareada, etc).
      - Evento de SERVOS vinculado a um evento de casais: resolve o par via evento_relacionado.
    """
    ev = insc.evento
    tipo_ev = (getattr(ev, "tipo", "") or "").lower()

    # Caso 1: evento de CASAIS Ã‚â€” pareamento direto
    if tipo_ev == "casais":
        par = _par_de(insc)
        if par and par.evento_id == insc.evento_id:
            return par
        return None

    # Caso 2: servos "de casal": achar par via evento_relacionado (que ÃƒÂ© de casais)
    rel = getattr(ev, "evento_relacionado", None)
    tipo_rel = (getattr(rel, "tipo", "") or "").lower() if rel else ""
    if tipo_ev == "servos" and rel and tipo_rel == "casais":
        # inscriÃƒÂ§ÃƒÂ£o deste participante no evento de casais
        insc_casal = Inscricao.objects.filter(evento=rel, participante_id=insc.participante_id).first()
        if not insc_casal:
            return None
        # o par no evento de casaisÃ‚â€¦
        par_casal = _par_de(insc_casal)
        if not par_casal:
            return None
        # Ã‚â€¦e a inscriÃƒÂ§ÃƒÂ£o do par no evento ATUAL (servos)
        return Inscricao.objects.filter(evento=ev, participante_id=par_casal.participante_id).first()

    return None

def _can_manage_inscricao(user, insc) -> bool:
    try:
        if getattr(user, "is_superuser", False):
            return True
        if hasattr(user, "is_admin_geral") and user.is_admin_geral():
            return True
    except Exception:
        pass
    if hasattr(user, "is_admin_paroquia") and user.is_admin_paroquia():
        return getattr(user, "paroquia_id", None) == getattr(insc, "paroquia_id", None)
    if getattr(user, "tipo_usuario", "") == "admin_paroquia":
        return getattr(user, "paroquia_id", None) == getattr(insc, "paroquia_id", None)
    return False

@login_required
@require_POST
def toggle_selecao_inscricao(request, inscricao_id):
    insc = get_object_or_404(Inscricao, id=inscricao_id)
    evento = insc.evento

    # --- PermissÃƒÂ£o (mesma regra da listagem) ---
    u = request.user
    try:
        is_admin_paroquia = bool(u.is_admin_paroquia())
    except Exception:
        is_admin_paroquia = (getattr(u, "tipo_usuario", "") == "admin_paroquia")

    try:
        is_admin_geral = bool(u.is_admin_geral())
    except Exception:
        is_admin_geral = bool(getattr(u, "is_superuser", False)) or (
            getattr(u, "tipo_usuario", "") == "admin_geral"
        )

    if is_admin_paroquia:
        if getattr(u, "paroquia_id", None) != getattr(evento, "paroquia_id", None):
            return HttpResponseForbidden("Acesso negado.")
    elif not is_admin_geral:
        return HttpResponseForbidden("Acesso negado.")

    # --- Parse do 'selected' ---
    val = (request.POST.get('selected') or '').strip().lower()
    wanted_selected = val in ('true', '1', 'on', 'yes', 'sim')

    # --- Helper para achar parceiro ---
    def _par_de(i: Inscricao):
        # pareamento dentro do mesmo evento (casais normalmente)
        try:
            if getattr(i, "par", None):
                return i.par
        except Exception:
            pass
        if getattr(i, "inscricao_pareada_id", None):
            return getattr(i, "inscricao_pareada", None)
        return getattr(i, "pareada_por", None)

    partner = None
    tipo_evento = (getattr(evento, "tipo", "") or "").lower()

    if tipo_evento == "casais":
        partner = _par_de(insc)

    elif tipo_evento == "servos":
        # Se for servos vinculados a casais, tentamos achar o parceiro via evento_relacionado (casais)
        rel = getattr(evento, "evento_relacionado", None)
        if rel and (getattr(rel, "tipo", "") or "").lower() == "casais":
            # 1) ache a inscriÃƒÂ§ÃƒÂ£o do participante no evento de casais
            insc_casal = (
                Inscricao.objects.filter(evento=rel, participante_id=insc.participante_id)
                .select_related("participante")
                .first()
            )
            if insc_casal:
                # 2) pegue o "par" nessa inscriÃƒÂ§ÃƒÂ£o de casais
                par_casal = _par_de(insc_casal)
                if par_casal and getattr(par_casal, "participante_id", None):
                    # 3) agora ache a inscriÃƒÂ§ÃƒÂ£o do PAR no prÃƒÂ³prio evento de servos
                    partner = (
                        Inscricao.objects.filter(evento=evento, participante_id=par_casal.participante_id)
                        .first()
                    )
        # fallback: se alguÃƒÂ©m armazenou pareamento direto tambÃƒÂ©m em servos
        if partner is None:
            partner = _par_de(insc)

    # --- PersistÃƒÂªncia (atual + parceiro) ---
    insc.foi_selecionado = wanted_selected
    insc.save(update_fields=["foi_selecionado"])

    partner_id = None
    if partner:
        partner.foi_selecionado = wanted_selected
        partner.save(update_fields=["foi_selecionado"])
        partner_id = partner.id

    return JsonResponse({
        "ok": True,
        "selected": wanted_selected,
        "partner_id": partner_id,
        "msg": "SeleÃƒÂ§ÃƒÂ£o atualizada" + (" (par tambÃƒÂ©m atualizado)" if partner_id else ""),
    })

from django.utils import timezone

@login_required
@require_POST
def alterar_status_inscricao(request, inscricao_id: int):
    """
    Regras pedidas:
    - 'Selecionado' (convocado) não gera pagamento.
    - Só 'Pagamento pendente' gera/garante objeto Pagamento com status PENDENTE.
    - 'Pagamento confirmado' apenas marca pagamento_confirmado=True e atualiza Pagamento para CONFIRMADO.
    - Sair de 'PAG_CONFIRMADO' volta pagamento_confirmado=False.
    - Sincroniza apenas 'foi_selecionado' do PAR (se houver). Pagamento é individual.
    """
    insc = get_object_or_404(Inscricao, id=inscricao_id)
    if not _can_manage_inscricao(request.user, insc):
        return HttpResponseForbidden("Acesso negado.")

    novo = (request.POST.get("status") or "").strip()
    validos = dict(InscricaoStatus.choices)
    if novo not in validos:
        return JsonResponse({"ok": False, "error": "status inválido"}, status=400)

    # Estados que contam como "selecionado"
    estados_selecionado = {
        InscricaoStatus.CONVOCADA,       # selecionado/convocado
        InscricaoStatus.PAG_PENDENTE,    # convocado e já com cobrança emitida
        InscricaoStatus.PAG_CONFIRMADO,  # convocado e pago
    }
    novo_sel = novo in estados_selecionado

    # Flags por status
    vai_confirmar_pagto = (novo == InscricaoStatus.PAG_CONFIRMADO)
    vai_deixar_pendente = (novo == InscricaoStatus.PAG_PENDENTE)

    par = _find_pair_in_same_event(insc)

    with transaction.atomic():
        updates = []

        # 1) Atualiza status
        if insc.status != novo:
            insc.status = novo
            updates.append("status")

        # 2) Atualiza seleção conforme o status novo
        if insc.foi_selecionado != novo_sel:
            insc.foi_selecionado = novo_sel
            updates.append("foi_selecionado")

        # 3) pagamento_confirmado reflete APENAS o status confirmado
        pagto_confirmado_bool = bool(getattr(insc, "pagamento_confirmado", False))
        if pagto_confirmado_bool != vai_confirmar_pagto:
            insc.pagamento_confirmado = vai_confirmar_pagto
            updates.append("pagamento_confirmado")

        if updates:
            insc.save(update_fields=updates)

        # 4) Sincroniza/garante o objeto Pagamento:
        #    - Em PAG_PENDENTE: cria se não existir e marca PENDENTE (NÃO confirma).
        #    - Em PAG_CONFIRMADO: cria/atualiza e confirma.
        #    - Nos demais: se existir, deixa PENDENTE (ou mantenha como está, a gosto).
        pgto = Pagamento.objects.filter(inscricao=insc).first()

        if vai_deixar_pendente:
            if pgto is None:
                pgto = Pagamento.objects.create(
                    inscricao=insc,
                    valor=insc.evento.valor_inscricao or 0,
                    metodo=getattr(Pagamento.MetodoPagamento, "PIX", "pix"),
                    status=Pagamento.StatusPagamento.PENDENTE,
                )
            else:
                if pgto.status != Pagamento.StatusPagamento.PENDENTE or pgto.data_pagamento:
                    pgto.status = Pagamento.StatusPagamento.PENDENTE
                    pgto.data_pagamento = None
                    pgto.save(update_fields=["status", "data_pagamento"])

        elif vai_confirmar_pagto:
            if pgto is None:
                pgto = Pagamento.objects.create(
                    inscricao=insc,
                    valor=insc.evento.valor_inscricao or 0,
                    metodo=getattr(Pagamento.MetodoPagamento, "PIX", "pix"),
                    status=Pagamento.StatusPagamento.CONFIRMADO,
                    data_pagamento=timezone.now(),
                )
            else:
                new_fields = []
                if pgto.status != Pagamento.StatusPagamento.CONFIRMADO:
                    pgto.status = Pagamento.StatusPagamento.CONFIRMADO
                    new_fields.append("status")
                if not pgto.data_pagamento:
                    pgto.data_pagamento = timezone.now()
                    new_fields.append("data_pagamento")
                if new_fields:
                    pgto.save(update_fields=new_fields)

        else:
            # Não é pendente nem confirmado -> não criamos pagamento novo.
            # Se já existe, opcionalmente o deixamos como PENDENTE (para manter rastreabilidade).
            if pgto and pgto.status != Pagamento.StatusPagamento.PENDENTE:
                pgto.status = Pagamento.StatusPagamento.PENDENTE
                pgto.data_pagamento = None
                pgto.save(update_fields=["status", "data_pagamento"])

        # 5) Se houver PAR, só espelhamos a seleção (não o status, nem pagamento)
        if par and par.foi_selecionado != novo_sel:
            par.foi_selecionado = novo_sel
            par.save(update_fields=["foi_selecionado"])

    return JsonResponse({
        "ok": True,
        "status": insc.status,
        "label": insc.get_status_display(),
        "pagamento_confirmado": bool(insc.pagamento_confirmado),
        "foi_selecionado": bool(insc.foi_selecionado),
        "paired_updated": bool(par),
    })

# inscricoes/views.py
import csv
import uuid
from typing import Optional
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify

from .models import EventoAcampamento, Inscricao


def _status_display(ins) -> str:
    return "Pago" if getattr(ins, "pagamento_confirmado", False) else "Pendente"


def _cidade_uf(ins) -> str:
    p = ins.participante
    cid = (getattr(p, "cidade", "") or "").strip()
    uf  = (getattr(p, "estado", "") or "").strip()
    return f"{cid}/{uf}" if cid and uf else (cid or uf or "")


@login_required
def relatorio_conferencia_pagamento(
    request,
    evento_id: Optional[uuid.UUID] = None,
    slug: Optional[str] = None,
):
    """
    - Aceita slug OU evento_id
    - Lista apenas inscriÃƒÂ§ÃƒÂµes selecionadas (foi_selecionado=True)
    - Mostra casal na MESMA LINHA: "Fulano - Sicrana"
    - Status (CÃƒÂ´njuge 1) e (CÃƒÂ´njuge 2) = Pago/Pendente
    - Filtro por cidade (?cidade=)
    - Exporta CSV (?csv=1) respeitando filtro
    """
    # 1) Resolver evento
    if evento_id:
        evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    elif slug:
        evento = get_object_or_404(EventoAcampamento, slug=slug)
    else:
        return HttpResponse("Evento nÃƒÂ£o informado.", status=400)

    # 2) Base: somente selecionados
    qs = (
        Inscricao.objects
        .filter(evento=evento, foi_selecionado=True)
        .select_related("participante", "paroquia")
        .order_by("participante__nome")
    )

    # 3) Filtro por cidade
    cidade = (request.GET.get("cidade") or "").strip()
    if cidade:
        qs = qs.filter(participante__cidade__iexact=cidade)

    # 4) Montagem das linhas (evita duplicar pares)
    def status_pag(ins) -> str:
        if getattr(ins, "pagamento_confirmado", False):
            return "Pago"
        if getattr(ins, "foi_selecionado", False):
            return "Pendente"
        return ""

    linhas = []
    vistos = set()

    for ins in qs:
        if ins.pk in vistos:
            continue

        par = getattr(ins, "par", None)  # property do seu model
        if par:
            vistos.update({ins.pk, par.pk})

            n1 = (ins.participante.nome or "").strip()
            n2 = (par.participante.nome or "").strip()
            if n2.lower() < n1.lower():
                ins, par = par, ins
                n1, n2 = n2, n1

            nome_dupla = f"{n1} - {n2}"
            status1 = status_pag(ins)
            status2 = status_pag(par)
            cidade_uf = _cidade_uf(ins)
            telefone = (ins.participante.telefone or par.participante.telefone or "").strip()
        else:
            vistos.add(ins.pk)
            nome_dupla = (ins.participante.nome or "").strip()
            status1 = status_pag(ins)
            status2 = ""
            cidade_uf = _cidade_uf(ins)
            telefone = (ins.participante.telefone or "").strip()

        linhas.append({
            "nome_dupla": nome_dupla,
            "cidade": cidade_uf,
            "telefone": telefone,
            "status1": status1,
            "status2": status2,
        })

    # 5) Ordena pela dupla
    linhas.sort(key=lambda r: r["nome_dupla"].upper())

    # 6) OpÃƒÂ§ÃƒÂµes de cidades (do universo de selecionados)
    cidades = list(
        Inscricao.objects
        .filter(evento=evento, foi_selecionado=True)
        .exclude(participante__cidade__isnull=True)
        .exclude(participante__cidade__exact="")
        .values_list("participante__cidade", flat=True)
        .distinct()
        .order_by("participante__cidade")
    )

    # 7) CSV
    if request.GET.get("csv") == "1":
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        nome_arq = f"conferencia-pagamento-{slugify(evento.nome)}.csv"
        resp["Content-Disposition"] = f'attachment; filename="{nome_arq}"'
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Nome (dupla)", "Cidade/UF", "Telefone", "Status (CÃƒÂ´njuge 1)", "Status (CÃƒÂ´njuge 2)"])
        for r in linhas:
            w.writerow([r["nome_dupla"], r["cidade"], r["telefone"], r["status1"], r["status2"]])
        return resp

    # 8) Render
    ctx = {
        "evento": evento,
        "linhas": linhas,
        "total": len(linhas),
        "cidades": cidades,
        "cidade_atual": cidade,
    }
    return render(request, "inscricoes/relatorio_conferencia_pagamento.html", ctx)

# inscricoes/views.py
from django.shortcuts import render, get_object_or_404
from django.db.models import Prefetch
from .models import EventoAcampamento, Ministerio, AlocacaoMinisterio

def relatorios_ministerios_overview(request, slug_evento):
    evento = get_object_or_404(EventoAcampamento, slug=slug_evento)
    # todos os ministÃƒÂ©rios que tÃƒÂªm pelo menos uma alocaÃƒÂ§ÃƒÂ£o nesse evento
    ministerios = (
        Ministerio.objects
        .filter(alocacoes__evento=evento)
        .distinct()
        .order_by("nome")
        .prefetch_related(
            Prefetch(
                "alocacoes",
                queryset=(
                    AlocacaoMinisterio.objects
                    .filter(evento=evento)
                    .select_related(
                        "inscricao",
                        "inscricao__participante",
                        "ministerio"
                    )
                    .order_by("-is_coordenador", "inscricao__participante__nome")
                ),
                to_attr="alocacoes_no_evento",
            )
        )
    )
    ctx = {
        "evento": evento,
        "ministerios": ministerios,
        "paroquia": evento.paroquia,
    }
    return render(request, "inscricoes/ministerios_overview.html", ctx)


def relatorios_ministerio_detail(request, slug_evento, ministerio_id):
    evento = get_object_or_404(EventoAcampamento, slug=slug_evento)
    ministerio = get_object_or_404(Ministerio, pk=ministerio_id)
    alocacoes = (
        AlocacaoMinisterio.objects
        .filter(evento=evento, ministerio=ministerio)
        .select_related("inscricao", "inscricao__participante", "ministerio")
        .order_by("-is_coordenador", "inscricao__participante__nome")
    )
    ctx = {
        "evento": evento,
        "ministerio": ministerio,
        "alocacoes": alocacoes,
        "paroquia": evento.paroquia,
    }
    return render(request, "inscricoes/ministerio_detail.html", ctx)

# inscricoes/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib import messages
from django.db.models import Count, Q
from django.views.decorators.http import require_POST
from django import forms

from .models import (
    EventoAcampamento, Grupo, AlocacaoGrupo, Inscricao
)

# -------------------- FORM --------------------
class GrupoForm(forms.ModelForm):
    class Meta:
        model = Grupo
        fields = ["nome", "cor_nome", "descricao"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do grupo/famÃƒÂ­lia"}),
            "cor_nome": forms.Select(attrs={"class": "form-select"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "DescriÃƒÂ§ÃƒÂ£o (opcional)"}),
        }


# -------------------- LISTA (HOME) --------------------
def grupos_evento_home(request, evento_id):
    """PÃƒÂ¡gina principal: lista os grupos e mostra contagem de membros no evento."""
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    grupos = (
        Grupo.objects.all()
        .annotate(qtd=Count("alocacoes", filter=Q(alocacoes__evento_id=evento.id)))
        .order_by("nome")
    )

    # para montar links bonitinhos com mesmo visual do sistema
    # vocÃƒÂª provavelmente jÃƒÂ¡ tem 'paroquia' nesse contexto Ã‚â€“ ajustei para usar evento.paroquia
    paroquia = getattr(evento, "paroquia", None)

    return render(
        request,
        "inscricoes/grupos_evento_home.html",
        {
            "evento": evento,
            "grupos": grupos,
            "paroquia": paroquia,
        },
    )


# -------------------- CRIAR GRUPO --------------------
def grupo_create(request):
    next_url = request.GET.get("next") or request.POST.get("next")

    if request.method == "POST":
        form = GrupoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Grupo/FamÃƒÂ­lia criado com sucesso.")
            # Volta para a pÃƒÂ¡gina que chamou (se houver), senÃƒÂ£o para o painel
            return redirect(next_url or "inscricoes:admin_paroquia_painel")
    else:
        form = GrupoForm()

    return render(
        request,
        "inscricoes/grupo_form_modal.html",
        {"form": form, "next": next_url},   # <- nada de 'evento' aqui
    )


# -------------------- DETALHE (EDITAR + MEMBROS) --------------------
def grupo_detail(request, grupo_id, evento_id):
    grupo = get_object_or_404(Grupo, pk=grupo_id)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if request.method == "POST":
        form = GrupoForm(request.POST, instance=grupo)
        if form.is_valid():
            form.save()
            messages.success(request, "Dados do grupo/famÃƒÂ­lia salvos.")
            return redirect("inscricoes:grupo_detail", grupo_id=grupo.id, evento_id=evento.id)
    else:
        form = GrupoForm(instance=grupo)

    # membros atuais do grupo neste evento
    membros = (
        AlocacaoGrupo.objects.select_related("inscricao__participante")
        .filter(evento=evento, grupo=grupo)
        .order_by("inscricao__participante__nome")
    )

    # outros grupos para 'mover'
    outros_grupos = Grupo.objects.exclude(pk=grupo.pk).order_by("nome")

    contexto = {
        "evento": evento,
        "grupo": grupo,
        "form": form,
        "membros": membros,
        "outros_grupos": outros_grupos,
        "paroquia": getattr(evento, "paroquia", None),
    }
    return render(request, "inscricoes/grupo_detail.html", contexto)


# -------------------- AJAX: BUSCAR INSCRITOS DO EVENTO --------------------
def buscar_inscritos_evento(request, evento_id):
    """
    Retorna inscritos do evento, filtrando por nome/CPF/email.
    ÃƒÅ¡til para popular a lista 'Adicionar pessoas' com toggle.
    """
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    q = (request.GET.get("q") or "").strip()

    qs = (
        Inscricao.objects.select_related("participante")
        .filter(evento=evento)
        .order_by("participante__nome")
    )
    if q:
        qs = qs.filter(
            Q(participante__nome__icontains=q)
            | Q(participante__email__icontains=q)
            | Q(participante__cpf__icontains=q)
        )

    # status rÃƒÂ¡pido: em qual grupo estÃƒÂ¡ (se estiver)
    aloc_map = {
        a.inscricao_id: a.grupo_id
        for a in AlocacaoGrupo.objects.filter(evento=evento, inscricao_id__in=qs.values_list("id", flat=True))
    }

    data = []
    for ins in qs[:50]:  # limite bÃƒÂ¡sico
        p = ins.participante
        data.append(
            {
                "inscricao_id": ins.id,
                "nome": p.nome,
                "email": p.email,
                "cpf": p.cpf,
                "grupo_id": aloc_map.get(ins.id),
            }
        )
    return JsonResponse({"results": data})


# -------------------- AJAX: TOGGLE MEMBRO (ADD/REMOVE) --------------------
@require_POST
def grupo_toggle_membro(request, grupo_id, evento_id):
    grupo = get_object_or_404(Grupo, pk=grupo_id)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    inscricao_id = request.POST.get("inscricao_id")
    if not inscricao_id:
        return HttpResponseBadRequest("inscricao_id ÃƒÂ© obrigatÃƒÂ³rio")

    try:
        ins = Inscricao.objects.get(pk=inscricao_id, evento=evento)
    except Inscricao.DoesNotExist:
        return HttpResponseBadRequest("InscriÃƒÂ§ÃƒÂ£o nÃƒÂ£o encontrada para este evento.")

    # verifica se jÃƒÂ¡ tem alocaÃƒÂ§ÃƒÂ£o
    aloc = AlocacaoGrupo.objects.filter(evento=evento, inscricao=ins).first()

    if aloc and aloc.grupo_id == grupo.id:
        # remover do grupo
        aloc.delete()
        return JsonResponse({"ok": True, "action": "removed"})
    else:
        # se estava em outro grupo, atualiza; se nÃƒÂ£o, cria
        if aloc:
            aloc.grupo = grupo
            aloc.save(update_fields=["grupo"])
        else:
            AlocacaoGrupo.objects.create(inscricao=ins, evento=evento, grupo=grupo)
        return JsonResponse({"ok": True, "action": "added"})


# -------------------- AJAX: MOVER MEMBRO PARA OUTRO GRUPO --------------------
@require_POST
def grupo_mover_membro(request):
    """
    Espera: inscricao_id, evento_id, target_grupo_id
    """
    inscricao_id = request.POST.get("inscricao_id")
    evento_id = request.POST.get("evento_id")
    target_grupo_id = request.POST.get("target_grupo_id")
    if not all([inscricao_id, evento_id, target_grupo_id]):
        return HttpResponseBadRequest("ParÃƒÂ¢metros obrigatÃƒÂ³rios ausentes.")

    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    target = get_object_or_404(Grupo, pk=target_grupo_id)

    try:
        ins = Inscricao.objects.get(pk=inscricao_id, evento=evento)
    except Inscricao.DoesNotExist:
        return HttpResponseBadRequest("InscriÃƒÂ§ÃƒÂ£o nÃƒÂ£o encontrada.")

    aloc, _ = AlocacaoGrupo.objects.get_or_create(inscricao=ins, evento=evento)
    aloc.grupo = target
    aloc.save(update_fields=["grupo"])

    return JsonResponse({"ok": True})

def _build_grupos_relatorio_queryset(evento, grupos_ids=None, somente_sem_grupo=False, busca=None, ordenar="grupo"):
    """
    Retorna (grupos, participantes_por_grupo, total_sem_grupo, total_geral)
    participantes_por_grupo: dict {Grupo|None: [Inscricao, ...]}
    """
    # base: inscriÃƒÂ§ÃƒÂµes do evento (todas; ajuste se quiser sÃƒÂ³ confirmados etc.)
    base_qs = (
        Inscricao.objects
        .filter(evento=evento)
        .select_related("participante")
        .only("id", "status", "participante__nome", "participante__cidade", "participante__estado")
    )

    if busca:
        base_qs = base_qs.filter(
            Q(participante__nome__icontains=busca) |
            Q(participante__cidade__icontains=busca)
        )

    # AlocaÃƒÂ§ÃƒÂ£o ? para saber o grupo (pode ser nulo)
    aloc_prefetch = Prefetch(
        "alocacao_grupo",
        queryset=AlocacaoGrupo.objects.select_related("grupo").only("id", "grupo_id"),
        to_attr="pref_aloc_grupo"
    )
    base_qs = base_qs.prefetch_related(aloc_prefetch)

    # carrega todas as inscriÃƒÂ§ÃƒÂµes (apÃƒÂ³s filtros)
    inscricoes = list(base_qs)

    # organiza por grupo (None = sem grupo)
    participantes_por_grupo = {}
    for ins in inscricoes:
        aloc = ins.pref_aloc_grupo[0] if getattr(ins, "pref_aloc_grupo", None) else None
        g = aloc.grupo if aloc and aloc.grupo_id else None
        participantes_por_grupo.setdefault(g, []).append(ins)

    # aplica filtros de grupos e sem-grupo
    grupos_filtrados = set()
    if grupos_ids:
        grupos_ids = {int(gid) for gid in grupos_ids if str(gid).isdigit()}
        grupos_filtrados = {g for g in participantes_por_grupo.keys() if (g and g.id in grupos_ids)}
    if somente_sem_grupo:
        grupos_filtrados = grupos_filtrados.union({None})

    if grupos_ids or somente_sem_grupo:
        # mantÃƒÂ©m apenas as chaves filtradas
        participantes_por_grupo = {
            g: lst for g, lst in participantes_por_grupo.items()
            if (g in grupos_filtrados)
        }

    # ordenaÃƒÂ§ÃƒÂ£o
    if ordenar == "nome":
        for g, lst in participantes_por_grupo.items():
            lst.sort(key=lambda i: (i.participante.nome or "").lower())
    else:  # padrÃƒÂ£o: por grupo, e dentro por nome
        # reordena dicionÃƒÂ¡rio por nome do grupo (None no fim)
        def gkey(g):
            return ("zzz" if g is None else (g.nome or "zzz")).lower()
        participantes_por_grupo = dict(sorted(participantes_por_grupo.items(), key=lambda kv: gkey(kv[0])))
        for lst in participantes_por_grupo.values():
            lst.sort(key=lambda i: (i.participante.nome or "").lower())

    # contagens auxiliares
    total_sem_grupo = len(participantes_por_grupo.get(None, []))
    total_geral = sum(len(v) for v in participantes_por_grupo.values())

    # lista de grupos do evento com contagem (para o filtro lateral/top)
    grupos_qs = (
        Grupo.objects
        .annotate(qtd=Count("alocacoes", filter=Q(alocacoes__evento=evento)))
        .order_by("nome")
    )

    return grupos_qs, participantes_por_grupo, total_sem_grupo, total_geral


def grupos_evento_relatorio(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # filtros
    grupos_ids = request.GET.getlist("grupos")  # multi-select
    somente_sem_grupo = request.GET.get("sem_grupo") == "1"
    busca = (request.GET.get("q") or "").strip()
    ordenar = request.GET.get("ord", "grupo")  # "grupo" | "nome"

    grupos, participantes_por_grupo, total_sem_grupo, total_geral = _build_grupos_relatorio_queryset(
        evento=evento,
        grupos_ids=grupos_ids,
        somente_sem_grupo=somente_sem_grupo,
        busca=busca,
        ordenar=ordenar,
    )

    context = {
        "evento": evento,
        "grupos": grupos,  # para filtros
        "participantes_por_grupo": participantes_por_grupo,
        "total_sem_grupo": total_sem_grupo,
        "total_geral": total_geral,
        "filtro": {
            "grupos": [int(x) for x in grupos_ids if str(x).isdigit()],
            "sem_grupo": somente_sem_grupo,
            "q": busca,
            "ord": ordenar,
        }
    }
    return render(request, "inscricoes/grupos_evento_relatorio.html", context)


def grupos_evento_relatorio_csv(request, evento_id):
    """Exporta CSV respeitando os mesmos filtros da pÃƒÂ¡gina HTML."""
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    grupos_ids = request.GET.getlist("grupos")
    somente_sem_grupo = request.GET.get("sem_grupo") == "1"
    busca = (request.GET.get("q") or "").strip()
    ordenar = request.GET.get("ord", "grupo")

    _, participantes_por_grupo, _, _ = _build_grupos_relatorio_queryset(
        evento=evento,
        grupos_ids=grupos_ids,
        somente_sem_grupo=somente_sem_grupo,
        busca=busca,
        ordenar=ordenar,
    )

    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Evento", evento.nome])
    writer.writerow([])
    writer.writerow(["Grupo", "Nome", "Cidade", "UF", "Status"])

    def group_name(g):
        return g.nome if g else "Ã‚â€” Sem grupo"

    for g, lst in participantes_por_grupo.items():
        gname = group_name(g)
        for ins in lst:
            p = ins.participante
            # pega o rÃƒÂ³tulo do status, se o mÃƒÂ©todo existir
            if hasattr(ins, "get_status_display"):
                status_label = ins.get_status_display()
            else:
                status_label = ins.status
            writer.writerow([gname, p.nome, p.cidade or "", p.estado or "", status_label])

    resp = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="relatorio-grupos-{evento.slug}.csv"'
    return resp

def _build_grupos_relatorio_queryset(*, evento, grupos_ids, somente_sem_grupo, busca, ordenar):
    """
    Retorna:
      - grupos: queryset para popular o filtro (com contagem no evento)
      - participantes_por_grupo: OrderedDict {Grupo|None: [Inscricao, ...]}
      - total_sem_grupo: int (no conjunto FILTRADO)
      - total_geral: int (no conjunto FILTRADO)
    """

    # 1) Grupos (para o filtro) com contagem de pessoas no EVENTO
    grupos = (
        Grupo.objects
        .annotate(qtd_evento=Count('alocacoes', filter=Q(alocacoes__evento=evento)))
        .order_by('nome')
    )

    # 2) Base: inscriÃƒÂ§ÃƒÂµes do evento, com participante e (possÃƒÂ­vel) alocaÃƒÂ§ÃƒÂ£o de grupo
    base = (
        Inscricao.objects
        .filter(evento=evento)
        .select_related('participante')
        .select_related('alocacao_grupo__grupo')
    )

    # 3) Busca por nome (se houver)
    if busca:
        base = base.filter(participante__nome__icontains=busca)

    # 4) Filtros de grupo
    # - se "somente_sem_grupo" estÃƒÂ¡ marcado, ignora "grupos_ids"
    if somente_sem_grupo:
        base = base.filter(alocacao_grupo__isnull=True)
    else:
        ids_validos = [int(x) for x in grupos_ids if str(x).isdigit()]
        if ids_validos:
            base = base.filter(alocacao_grupo__grupo_id__in=ids_validos)

    # 5) OrdenaÃƒÂ§ÃƒÂ£o
    if ordenar == "nome":
        base = base.order_by('participante__nome')
    else:
        # por grupo: primeiro com grupo pelo nome, depois Ã‚â€œSem grupoÃ‚â€
        # Dica: ordenamos em Python quando vamos montar os buckets
        pass

    # 6) Monta buckets {grupo: [inscricoes]}
    buckets = {}
    for ins in base:
        g = getattr(getattr(ins, 'alocacao_grupo', None), 'grupo', None)
        buckets.setdefault(g, []).append(ins)

    # OrdenaÃƒÂ§ÃƒÂ£o por grupo (alÃƒÂ©m da ordem interna dos itens, caso pedir por nome jÃƒÂ¡ veio ordenado)
    def _k_group(gr):
        # grupos com nome vÃƒÂªm primeiro, "None" (sem grupo) por ÃƒÂºltimo
        if gr is None:
            return (1, "ZZZZZZ")  # joga para o fim
        return (0, gr.nome or "")
    participantes_por_grupo = OrderedDict(sorted(buckets.items(), key=lambda kv: _k_group(kv[0])))

    # 7) Contagens (no conjunto FILTRADO)
    total_geral = sum(len(lst) for lst in participantes_por_grupo.values())
    total_sem_grupo = len(participantes_por_grupo.get(None, []))

    return grupos, participantes_por_grupo, total_sem_grupo, total_geral

# views.py

def grupos_evento_relatorio_print(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    grupos_ids = request.GET.getlist("grupos")
    try:
        grupos_ids_int = [int(x) for x in grupos_ids if str(x).isdigit()]
    except Exception:
        grupos_ids_int = []

    somente_sem_grupo = (request.GET.get("sem_grupo") == "1")
    busca = (request.GET.get("q") or "").strip()
    ordenar = request.GET.get("ord", "grupo").lower()
    if ordenar not in {"grupo", "nome"}:
        ordenar = "grupo"

    # AQUI: pegue a lista de grupos tambÃƒÂ©m
    grupos, participantes_por_grupo, total_sem_grupo, total_geral = _build_grupos_relatorio_queryset(
        evento=evento,
        grupos_ids=grupos_ids_int,
        somente_sem_grupo=somente_sem_grupo,
        busca=busca,
        ordenar=ordenar,
    )

    context = {
        "evento": evento,
        "grupos": grupos,  # <- necessÃƒÂ¡rio para renderizar as caixinhas
        "participantes_por_grupo": participantes_por_grupo,
        "total_sem_grupo": total_sem_grupo,
        "total_geral": total_geral,
        "filtro": {
            "q": busca,
            "grupos": grupos_ids_int,
            "sem_grupo": somente_sem_grupo,
            "ord": ordenar,
        },
        "qs": request.GET.urlencode(),
    }
    return render(request, "inscricoes/grupos_evento_relatorio_print.html", context)

def _is_admin_geral(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "tipo_usuario", "") == "admin_geral")

Q2 = Decimal("0.01")
def _q2(v) -> Decimal:
    """Arredonda com 2 casas, aceitando str/Decimal/float."""
    if v is None:
        return Decimal("0.00")
    if not isinstance(v, Decimal):
        v = Decimal(str(v))
    return v.quantize(Q2, rounding=ROUND_HALF_UP)

def _is_admin_geral(user) -> bool:
    return getattr(user, "tipo_usuario", "") == "admin_geral"

def _is_admin_paroquia_do_repasse(user, rep: Repasse) -> bool:
    return getattr(user, "tipo_usuario", "") == "admin_paroquia" and getattr(user, "paroquia_id", None) == rep.paroquia_id


def _is_admin_geral(user) -> bool:
    return getattr(user, "is_authenticated", False) and getattr(user, "tipo_usuario", "") == "admin_geral"

def _is_admin_paroquia_of(user, paroquia) -> bool:
    return (
        getattr(user, "is_authenticated", False)
        and getattr(user, "tipo_usuario", "") == "admin_paroquia"
        and getattr(user, "paroquia_id", None) == getattr(paroquia, "id", None)
    )

# ---------- helper de quantizaÃƒÂ§ÃƒÂ£o ----------
def _q2(x) -> Decimal:
    """Converte para Decimal(2 casas) de forma tolerante (str/float/Decimal)."""
    d = Decimal(str(x)).quantize(Decimal("0.01"))
    return d

@require_POST
def gerar_repasse(request, evento_id):
    if not _is_admin_geral(request.user):
        return HttpResponseForbidden("Apenas Admin Geral.")

    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    owner_cfg = MercadoPagoOwnerConfig.objects.filter(ativo=True).first()
    if not owner_cfg:
        messages.error(request, "ConfiguraÃƒÂ§ÃƒÂ£o do Mercado Pago (dono) nÃƒÂ£o encontrada/ativa.")
        return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)

    # Entradas do form
    try:
        base = _q2(request.POST.get("repasse_base") or "0")
        taxa_percentual = _q2(request.POST.get("repasse_percentual") or "0")
        override = _q2(request.POST.get("repasse_valor_override") or "0")
        if base <= 0 or taxa_percentual < 0 or taxa_percentual > 100:
            raise InvalidOperation
    except Exception:
        messages.error(request, "Valores invÃƒÂ¡lidos para base ou percentual.")
        return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)

    # CÃƒÂ¡lculo do repasse: usa override (>0) se veio do form; senÃƒÂ£o calcula
    valor_calc = _q2(base * (taxa_percentual / Decimal("100")))
    valor_repasse = override if override > 0 else valor_calc
    if valor_repasse <= 0:
        messages.error(request, "Valor de repasse deve ser maior que zero.")
        return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)

    # Garante nÃƒÂ£o haver PENDENTE duplicado (constraint + lock)
    try:
        with transaction.atomic():
            existe_pendente = Repasse.objects.select_for_update().filter(
                paroquia=evento.paroquia,
                evento=evento,
                status=Repasse.Status.PENDENTE,
            ).exists()
            if existe_pendente:
                messages.warning(request, "JÃƒÂ¡ existe um repasse PENDENTE para este evento/parÃƒÂ³quia.")
                return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)

            # Gera cobranÃƒÂ§a PIX na CONTA DO DONO (mock seguro por enquanto)
            svc = MercadoPagoOwnerService(
                access_token=owner_cfg.access_token,
                notif_url=owner_cfg.notificacao_webhook_url,  # campo do seu model
            )
            pix = svc.create_pix_charge(
                descricao=f"Repasse {evento.nome} ({taxa_percentual}%)",
                valor_decimal=valor_repasse,
            )

            rep = Repasse.objects.create(
                paroquia=evento.paroquia,
                evento=evento,
                valor_base=_q2(base),
                taxa_percentual=_q2(taxa_percentual),
                valor_repasse=_q2(valor_repasse),
                status=Repasse.Status.PENDENTE,
                transacao_id=getattr(pix, "id", None),
                qr_code_text=getattr(pix, "qr_code_text", None),
                qr_code_base64=getattr(pix, "qr_code_base64", None),
            )

    except IntegrityError:
        messages.error(request, "NÃƒÂ£o foi possÃƒÂ­vel criar: jÃƒÂ¡ existe um repasse pendente para este evento/parÃƒÂ³quia.")
        return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)
    except Exception as e:
        messages.error(request, f"Falha ao gerar PIX do repasse: {e}")
        return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)

    messages.success(request, "Repasse gerado com sucesso. Exiba o QR para a parÃƒÂ³quia realizar o pagamento.")
    return redirect("inscricoes:relatorio_financeiro", evento_id=evento.id)


@require_GET
def repasse_qr(request, repasse_id):
    rep = get_object_or_404(Repasse, pk=repasse_id)

    # Admin Geral OU Admin da MESMA parÃƒÂ³quia
    if not (_is_admin_geral(request.user) or _is_admin_paroquia_of(request.user, rep.paroquia)):
        return HttpResponseForbidden("Apenas Admin Geral ou Admin da ParÃƒÂ³quia.")

    if rep.status != Repasse.Status.PENDENTE:
        raise Http404("Repasse nÃƒÂ£o estÃƒÂ¡ pendente.")

    # 1) Se jÃƒÂ¡ temos imagem base64, sÃƒÂ³ renderiza.
    if rep.qr_code_base64:
        return render(request, "inscricoes/repasse_qr_modal.html", {"repasse": rep, "qr_warning": None})

    # 2) Se temos "texto", precisamos garantir que ÃƒÂ© o payload EMV.
    txt = (rep.qr_code_text or "").strip()
    qr_warning = None

    if not txt:
        qr_warning = "Provedor nÃƒÂ£o retornou o payload do QR (qr_code_text vazio)."
    else:
        # Caso comum de erro: colocam a IMAGEM base64 em qr_code_text
        if txt.startswith("data:image/"):
            # extrai o puro base64
            try:
                b64 = txt.split(",", 1)[1]
                # valida base64
                base64.b64decode(b64, validate=True)
                rep.qr_code_base64 = b64
                rep.save(update_fields=["qr_code_base64"])
                return render(request, "inscricoes/repasse_qr_modal.html", {"repasse": rep, "qr_warning": None})
            except Exception:
                qr_warning = "ConteÃƒÂºdo em qr_code_text parece uma imagem base64 invÃƒÂ¡lida."

        # Remove espaÃƒÂ§os e quebras (alguns gateways mandam com \n)
        txt_clean = re.sub(r"\s+", "", txt)

        # ValidaÃƒÂ§ÃƒÂ£o leve de EMV PIX: comeÃƒÂ§a 000201 e contÃƒÂ©m CRC tag 63
        looks_like_emv = txt_clean.startswith("000201") and "6304" in txt_clean
        if not looks_like_emv:
            qr_warning = (
                "O texto recebido nÃƒÂ£o parece um payload EMV do PIX. "
                "Verifique se estÃƒÂ¡ usando o campo correto do provedor."
            )
        else:
            # 3) Gerar PNG a partir do payload EMV
            if not qrcode:
                qr_warning = (
                    "Biblioteca 'qrcode' nÃƒÂ£o instalada. Execute: pip install 'qrcode[pil]' "
                    "ou use o copia-e-cola abaixo."
                )
            else:
                try:
                    buf = io.BytesIO()
                    qrcode.make(txt_clean).save(buf, format="PNG")
                    rep.qr_code_base64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    # IMPORTANTE: salve o texto saneado tambÃƒÂ©m
                    if txt_clean != rep.qr_code_text:
                        rep.qr_code_text = txt_clean
                        rep.save(update_fields=["qr_code_base64", "qr_code_text"])
                    else:
                        rep.save(update_fields=["qr_code_base64"])
                except Exception as e:
                    qr_warning = f"Falha ao gerar a imagem do QR: {e}"

    return render(request, "inscricoes/repasse_qr_modal.html", {"repasse": rep, "qr_warning": qr_warning})

def _get_base(inscricao):
    """
    Devolve a base de inscriÃƒÂ§ÃƒÂ£o (qualquer tipo) jÃƒÂ¡ existente para esta inscriÃƒÂ§ÃƒÂ£o.
    Trata corretamente OneToOne quando nÃƒÂ£o existe (evita lanÃƒÂ§ar DoesNotExist).
    """
    if not inscricao:
        return None

    # tenta nas relaÃƒÂ§ÃƒÂµes conhecidas (ordem dÃƒÂ¡ preferÃƒÂªncia a casais/servos)
    for rel in (
        "inscricaocasais",
        "inscricaoservos",
        "inscricaosenior",
        "inscricaojuvenil",
        "inscricaomirim",
        "inscricaoevento",
        "inscricaoretiro",
    ):
        try:
            obj = getattr(inscricao, rel)
            if obj:
                return obj
        except ObjectDoesNotExist:
            # essa relaÃƒÂ§ÃƒÂ£o OneToOne nÃƒÂ£o existe para esta inscriÃƒÂ§ÃƒÂ£o Ã¢â‚¬â€ segue
            continue
        except AttributeError:
            # relaÃƒÂ§ÃƒÂ£o nÃƒÂ£o existe no modelo atual Ã¢â‚¬â€ segue
            continue

    # fallback via mÃƒÂ©todo do prÃƒÂ³prio modelo, caso mude os nomes das relaÃƒÂ§ÃƒÂµes no futuro
    try:
        Model = inscricao._get_baseinscricao_model()
        if Model:
            return Model.objects.select_related("paroquia", "pastoral_movimento").filter(inscricao=inscricao).first()
    except Exception:
        pass

    return None


def _evento_eh_casais_ou_servos_de_casais(evento) -> bool:
    tipo = (getattr(evento, "tipo", "") or "").lower()
    if tipo == "casais":
        return True
    if tipo == "servos":
        principal = getattr(evento, "evento_relacionado", None)
        if principal and (getattr(principal, "tipo", "") or "").lower() == "casais":
            return True
    return False


# --- HOTFIXS API CN + FICHA ---

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET
from django.shortcuts import render, get_object_or_404

from .models import Inscricao

@require_GET
def cn_leituras_hoje(request: HttpRequest):
    # TODO: implementar integraÃƒÂ§ÃƒÂ£o real
    return JsonResponse({
        "ok": True,
        "endpoint": "cn_leituras_hoje",
        "date": str(timezone.localdate()),
        "data": None,
        "msg": "stub",
    })

@require_GET
def cn_santo_hoje(request: HttpRequest):
    # TODO: implementar integraÃƒÂ§ÃƒÂ£o real
    return JsonResponse({
        "ok": True,
        "endpoint": "cn_santo_hoje",
        "date": str(timezone.localdate()),
        "data": None,
        "msg": "stub",
    })

def _safe_get_related_fields(model_cls, candidates):
    """
    Retorna apenas os nomes de campo de `candidates` que realmente existem
    no modelo (evita passar nomes inválidos para select_related).
    """
    valid = []
    for name in candidates:
        try:
            model_cls._meta.get_field(name)
            valid.append(name)
        except Exception:
            # campo não existe -> ignora
            continue
    return valid

def _get_payments_for(insc) -> Optional[QuerySet]:
    """
    Tenta retornar um queryset/lista com pagamentos relacionados à inscrição.
    Suporta nomes comuns: pagamentos, pagamento_set, pagamento (FK), payments...
    """
    if insc is None:
        return None

    # possíveis reverse names / campos
    candidates = ['pagamentos', 'pagamento_set', 'payments', 'payment_set']
    for cand in candidates:
        if hasattr(insc, cand):
            attr = getattr(insc, cand)
            try:
                # se for manager/queryset
                if hasattr(attr, 'all'):
                    return attr.all()
                # se for um objeto único
                return [attr]
            except Exception:
                continue

    # se existir um campo direto chamado 'pagamento' e não for None
    if hasattr(insc, 'pagamento') and getattr(insc, 'pagamento') is not None:
        return [getattr(insc, 'pagamento')]

    # fallback: tenta varrer todos os fields do modelo procurando por FK para um modelo Pagamento (rudimentar)
    # (comentado para não fazer queries desnecessárias — ative se quiser lógica extra)
    return None

def _latest_payment(payments: Optional[Iterable]) -> Optional[Any]:
    if not payments:
        return None
    try:
        if isinstance(payments, QuerySet):
            return payments.order_by('-id').first()
        # lista Python
        return payments[-1] if len(payments) else None
    except Exception:
        try:
            return list(payments)[-1]
        except Exception:
            return None

def _find_transaction_id(obj) -> Optional[str]:
    """
    Procura atributos comumente usados para guardar id de transação.
    """
    if obj is None:
        return None
    for attr in ('transacao_id', 'transaction_id', 'tx_id', 'pagamento_transacao', 'pagamento_id'):
        val = getattr(obj, attr, None)
        if val:
            return val
    return None

def _resolve_base_safe(insc: Optional[Inscricao]):
    """
    Retorna o objeto 'base' ligado à inscrição (um dos OneToOne):
    inscricaosenior / inscricaojuvenil / inscricaomirim / inscricaoservos /
    inscricaocasais / inscricaoevento / inscricaoretiro.
    Se nada existir, retorna None.
    """
    if not insc:
        return None
    for attr in (
        "inscricaosenior", "inscricaojuvenil", "inscricaomirim",
        "inscricaoservos", "inscricaocasais", "inscricaoevento", "inscricaoretiro"
    ):
        if hasattr(insc, attr):
            try:
                obj = getattr(insc, attr)
                if obj:  # se a relação existir
                    return obj
            except Exception:
                # OneToOne inexistente não quebra
                pass
    return None

def _get_pagamento(insc: Optional[Inscricao]) -> Optional[Pagamento]:
    """Como Pagamento é OneToOne, tenta pegar com filter().first() para não levantar DoesNotExist."""
    if not insc:
        return None
    try:
        return Pagamento.objects.filter(inscricao=insc).order_by("-data_pagamento").first()
    except Exception:
        return None

def _latest_payment(payments_or_obj: Any) -> Optional[Pagamento]:
    """Compat: se já for um Pagamento, retorna; se for lista/qs, pega o primeiro; se None, None."""
    if payments_or_obj is None:
        return None
    if isinstance(payments_or_obj, Pagamento):
        return payments_or_obj
    try:
        return payments_or_obj[0] if payments_or_obj else None
    except Exception:
        return None

def _find_transaction_id(obj: Any) -> Optional[str]:
    """Procura um campo de transação em obj (Pagamento ou Inscricao)."""
    if obj is None:
        return None
    for attr in ("transacao_id", "transaction_id", "txid", "tx_id"):
        v = getattr(obj, attr, None)
        if v:
            return str(v)
    return None

def _is_paid(obj: Any, last_payment: Optional[Pagamento] = None) -> bool:
    """Checa flags comuns de pagamento em Inscricao e Pagamento."""
    if obj is not None:
        for attr in ("pagamento_confirmado", "inscricao_concluida", "confirmado", "paid", "is_paid"):
            v = getattr(obj, attr, None)
            if isinstance(v, bool) and v:
                return True
    if last_payment is not None:
        for attr in ("status", "pagamento_confirmado", "confirmado", "paid", "is_paid"):
            v = getattr(last_payment, attr, None)
            # status pode ser uma string 'confirmado'
            if isinstance(v, bool) and v:
                return True
            if isinstance(v, str) and v.lower() in {"confirmado", "paid", "pago"}:
                return True
    return False


@login_required
def ficha_casal_paisagem(request, pk: int):
    """
    Monta o contexto completo para o template 'inscricoes/ficha_casal_paisagem.html'
    - a: inscrição principal
    - b: par (se houver)
    - base_a, base_b: objetos-base (um dos: inscricaosenior/juvenil/mirim/servos/casais/evento/retiro)
    - pagamentos/transações de A e B
    - evento, política (se disponível), contatos de suporte (fallback em settings)
    """

    # Carrega a inscrição com relacionamentos reais do teu modelo
    inscricao = get_object_or_404(
        Inscricao.objects.select_related(
            "participante",
            "paroquia",
            "evento",
            "inscricao_pareada",
            "inscricao_pareada__participante",
            "inscricao_pareada__paroquia",
        ),
        pk=pk,
    )

    a = inscricao
    b = getattr(inscricao, "par", None)  # property já existente no teu modelo

    # Bases seguras (sem import de submódulos)
    base_a = _resolve_base_safe(a)
    base_b = _resolve_base_safe(b) if b else None

    # Pagamentos A/B
    pay_a = _get_pagamento(a)
    pay_b = _get_pagamento(b) if b else None
    latest_payment_a = _latest_payment(pay_a)
    latest_payment_b = _latest_payment(pay_b)

    transacao_a = _find_transaction_id(latest_payment_a) or _find_transaction_id(a)
    transacao_b = _find_transaction_id(latest_payment_b) or _find_transaction_id(b)

    pagamento_confirmado_a = _is_paid(a, latest_payment_a)
    pagamento_confirmado_b = _is_paid(b, latest_payment_b) if b else False

    # Evento / política / suporte (tolerante)
    evento = getattr(inscricao, "evento", None)
    politica = None
    suporte_email = getattr(settings, "SUPORTE_EMAIL", None)
    suporte_whatsapp_link = getattr(settings, "SUPORTE_WHATSAPP", None)

    try:
        if evento:
            # tenta achar política via evento ou via paroquia associada
            if hasattr(evento, "politica") and getattr(evento, "politica"):
                politica = evento.politica
            elif hasattr(evento, "paroquia") and getattr(evento, "paroquia", None):
                # se o projeto tiver alguma ligação com política na paróquia:
                politica = getattr(evento.paroquia, "politica", None) or politica

            # sobrepor suporte se existir no evento
            suporte_email = getattr(evento, "suporte_email", None) or suporte_email
            suporte_whatsapp_link = getattr(evento, "suporte_whatsapp_link", None) or suporte_whatsapp_link
    except Exception:
        pass

    context: Dict[str, Any] = {
        "inscricao": inscricao,
        "a": a,
        "b": b,
        "base_a": base_a,
        "base_b": base_b,
        "evento": evento,
        "payments_a": pay_a,
        "latest_payment_a": latest_payment_a,
        "transacao_a": transacao_a,
        "pagamento_confirmado_a": pagamento_confirmado_a,
        "payments_b": pay_b,
        "latest_payment_b": latest_payment_b,
        "transacao_b": transacao_b,
        "pagamento_confirmado_b": pagamento_confirmado_b,
        "politica": politica,
        "suporte_email": suporte_email,
        "suporte_whatsapp_link": suporte_whatsapp_link,
    }
    return render(request, "inscricoes/ficha_casal_paisagem.html", context)

@require_POST
def toggle_pagamento_inscricao(request, inscricao_id):
    """
    Marca/desmarca pagamento de uma inscrição.
    Recebe POST {'mark_paid': 'true'|'false'}.
    Cria um pagamento caso não exista e marque como confirmado.
    A view é defensiva: só usa campos que existam no modelo Pagamento.
    """
    inscricao = get_object_or_404(Inscricao, pk=inscricao_id)
    mark_paid = request.POST.get('mark_paid', 'true').lower() == 'true'

    # lista de campos concretos do modelo Pagamento
    pagamento_fields = {f.name for f in Pagamento._meta.fields}

    try:
        with transaction.atomic():
            if mark_paid:
                # procura pagamento pendente (várias convenções de status)
                pagamento = Pagamento.objects.filter(inscricao=inscricao).order_by('-id').first()

                if pagamento:
                    # tenta marcar o pagamento como confirmado de forma segura
                    if 'status' in pagamento_fields:
                        # algumas implementações usam 'pendente'/'confirmado'
                        try:
                            pagamento.status = 'confirmado'
                        except Exception:
                            # campo pode ser choice; para não quebrar, setamos se possível
                            pass
                    if 'confirmado' in pagamento_fields:
                        setattr(pagamento, 'confirmado', True)
                    if 'confirmado_em' in pagamento_fields:
                        setattr(pagamento, 'confirmado_em', timezone.now())
                    if 'data_confirmacao' in pagamento_fields:
                        setattr(pagamento, 'data_confirmacao', timezone.now())
                    pagamento.save()
                    created = False
                else:
                    # cria um pagamento novo com apenas campos suportados
                    create_kwargs = {}
                    if 'inscricao' in pagamento_fields:
                        create_kwargs['inscricao'] = inscricao
                    if 'valor' in pagamento_fields:
                        # tenta buscar valor do evento, senão 0
                        create_kwargs['valor'] = getattr(inscricao.evento, 'valor_inscricao', 0) if hasattr(inscricao, 'evento') else 0
                    if 'status' in pagamento_fields:
                        create_kwargs['status'] = 'confirmado'
                    if 'confirmado' in pagamento_fields:
                        create_kwargs['confirmado'] = True
                    if 'confirmado_em' in pagamento_fields:
                        create_kwargs['confirmado_em'] = timezone.now()
                    if 'data_confirmacao' in pagamento_fields:
                        create_kwargs['data_confirmacao'] = timezone.now()

                    pagamento = Pagamento.objects.create(**create_kwargs)
                    created = True

                # sincroniza campo de flag na inscrição se existir
                if hasattr(inscricao, 'pagamento_confirmado'):
                    inscricao.pagamento_confirmado = True
                    inscricao.save(update_fields=['pagamento_confirmado'])

                return JsonResponse({
                    'ok': True,
                    'pagamento_confirmado': True,
                    'created_pagamento': created,
                    'msg': 'Pagamento registrado e inscrição marcada como paga.'
                })

            else:
                # desmarcar como pago: não apaga histórico, apenas atualiza estado
                # atualiza último pagamento ligado e/ou a flag da inscrição
                pagamento = Pagamento.objects.filter(inscricao=inscricao).order_by('-id').first()
                if pagamento:
                    if 'status' in pagamento_fields:
                        pagamento.status = 'pendente'  # ou outro valor que faça sentido
                    if 'confirmado' in pagamento_fields:
                        setattr(pagamento, 'confirmado', False)
                    if 'confirmado_em' in pagamento_fields and 'confirmado_em' in pagamento_fields:
                        # se existir campo de data, podemos zerar (opcional)
                        try:
                            setattr(pagamento, 'confirmado_em', None)
                        except Exception:
                            pass
                    pagamento.save()

                if hasattr(inscricao, 'pagamento_confirmado'):
                    inscricao.pagamento_confirmado = False
                    inscricao.save(update_fields=['pagamento_confirmado'])

                return JsonResponse({'ok': True, 'pagamento_confirmado': False, 'msg': 'Pagamento desmarcado.'})

    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

# views.py
from django.apps import apps
from inscricoes.models import Inscricao

def _safe_get_baseinscricao_model(self):
    """Substitui o método problemático sem alterar o models.py."""
    tipo = (getattr(self.evento, "tipo", "") or "").strip().lower()
    mapping = {
        'senior':  ('inscricoes', 'InscricaoSenior'),
        'juvenil': ('inscricoes', 'InscricaoJuvenil'),
        'mirim':   ('inscricoes', 'InscricaoMirim'),
        'servos':  ('inscricoes', 'InscricaoServos'),
        'casais':  ('inscricoes', 'InscricaoCasais'),
        'evento':  ('inscricoes', 'InscricaoEvento'),
        'retiro':  ('inscricoes', 'InscricaoRetiro'),
    }
    app_label, model_name = mapping.get(tipo, (None, None))
    return apps.get_model(app_label, model_name) if app_label else None

# Monkey patch (executa 1x)
if getattr(Inscricao, "_get_baseinscricao_model", None) is not _safe_get_baseinscricao_model:
    Inscricao._get_baseinscricao_model = _safe_get_baseinscricao_model


SELECIONADOS = {
    InscricaoStatus.CONVOCADA,
    InscricaoStatus.PAG_PENDENTE,
    InscricaoStatus.PAG_CONFIRMADO,
}

def _resolve_base(inscricao):
    """
    Resolve a BaseInscricao da inscrição SEM tocar no models.py.
    Usa o tipo do evento para acessar o related_name OneToOne e,
    se não achar, tenta os relacionamentos conhecidos como fallback.
    """
    if not inscricao:
        return None

    tipo = (getattr(inscricao.evento, "tipo", "") or "").strip().lower()

    # mapeia tipo -> related_name existente no OneToOne
    rel_por_tipo = {
        "senior":  "inscricaosenior",
        "juvenil": "inscricaojuvenil",
        "mirim":   "inscricaomirim",
        "servos":  "inscricaoservos",
        "casais":  "inscricaocasais",
        "evento":  "inscricaoevento",
        "retiro":  "inscricaoretiro",
    }

    # 1) Tenta pelo tipo do evento
    rel = rel_por_tipo.get(tipo)
    if rel:
        try:
            return getattr(inscricao, rel)
        except ObjectDoesNotExist:
            return None
        except AttributeError:
            pass  # cairá no fallback

    # 2) Fallback robusto: tenta todos os related_names conhecidos
    for relname in (
        "inscricaocasais",
        "inscricaosenior",
        "inscricaojuvenil",
        "inscricaomirim",
        "inscricaoservos",
        "inscricaoevento",
        "inscricaoretiro",
    ):
        try:
            return getattr(inscricao, relname)
        except ObjectDoesNotExist:
            continue
        except AttributeError:
            continue

    return None

SELECIONADOS = {
    InscricaoStatus.CONVOCADA,
    InscricaoStatus.PAG_PENDENTE,
    InscricaoStatus.PAG_CONFIRMADO,
}

def _resolve_base(inscricao):
    Model = inscricao._get_baseinscricao_model()
    if not Model:
        return None
    try:
        return Model.objects.get(inscricao=inscricao)
    except Model.DoesNotExist:
        return None

@login_required
def todas_as_fichas_evento_casal(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)

    filtro = (request.GET.get("filtro") or "todos").lower()
    qs = (
        Inscricao.objects
        .filter(evento=evento)
        .select_related(
            "participante", "paroquia", "evento",
            "inscricao_pareada",
            "inscricao_pareada__participante", "inscricao_pareada__paroquia",
        )
        .prefetch_related(
            "inscricaosenior", "inscricaojuvenil", "inscricaomirim",
            "inscricaoservos", "inscricaocasais", "inscricaoevento", "inscricaoretiro",
            "inscricao_pareada__inscricaosenior", "inscricao_pareada__inscricaojuvenil",
            "inscricao_pareada__inscricaomirim", "inscricao_pareada__inscricaoservos",
            "inscricao_pareada__inscricaocasais", "inscricao_pareada__inscricaoevento",
            "inscricao_pareada__inscricaoretiro",
        )
        .order_by("participante__nome")
    )

    if filtro == "selecionados":
        qs = qs.filter(status__in=SELECIONADOS)
    elif filtro == "nao_selecionados":
        qs = qs.exclude(status__in=SELECIONADOS)
    else:
        filtro = "todos"

    sheets = []
    ja_impresso = set()
    for a in qs:
        if a.id in ja_impresso:
            continue

        b = getattr(a, "par", None)
        if b:
            menor, maior = (a, b) if a.id <= b.id else (b, a)
            if a != menor:
                continue
            ja_impresso.add(maior.id)

        base_a = _resolve_base(a)
        base_b = _resolve_base(b) if b else None

        sheets.append({
            "a": a,
            "b": b,
            "base_a": base_a,
            "base_b": base_b,
            "evento": evento,
        })

    contexto = { "evento": evento, "sheets": sheets, "filtro": filtro }
    return render(request, "inscricoes/fichas_evento_print.html", contexto)