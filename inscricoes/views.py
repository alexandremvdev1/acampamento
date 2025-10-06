# ——— Python stdlib
import os
import csv
import json
import logging
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
# ——— Terceiros
import mercadopago
import qrcode
from django.forms import modelform_factory

# ——— App (helpers, models, forms)
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

# --- PROGRESSO DA INSCRIÇÃO (ordem: endereço -> personalizado -> contato -> saúde) ---



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

    # 0) Endereço (fica dentro de 'inscricao_inicial', retomamos via querystring)
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

    # 3) Saúde (marca envio ao salvar)
    if not insc.inscricao_enviada:
        return {"step": "saude", "next_url": reverse("inscricoes:formulario_saude", args=[insc.id])}

    # 4) Depois do envio: se selecionado e não pago → pagamento; senão → status
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
    # Supondo que o usuário tenha atributo 'paroquia' diretamente ou via perfil
    paroquia = getattr(request.user, 'paroquia', None)
    nome_paroquia = paroquia.nome if paroquia else 'Sem Paróquia'
    return HttpResponse(f"Bem-vindo, Admin da Paróquia: {nome_paroquia}")

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
    return render(request, 'inscricoes/admin_geral_confirm_delete.html', {'obj': paroquia, 'tipo': 'Paróquia'})

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
        return HttpResponse("Status inválido.", status=400)
    paroquia.status = status
    paroquia.save(update_fields=["status"])
    messages.success(request, f"Paróquia marcada como {status}.")
    return redirect(request.POST.get("next") or reverse("inscricoes:admin_geral_list_paroquias"))
# -------- Usuários Admin Paróquia --------
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

    # se vier explicitamente active=true/false, usa; senão alterna
    if "active" in request.POST:
        ativa = (request.POST.get("active") or "").strip().lower() in {"1","true","on","yes","sim"}
    else:
        ativa = (paroquia.status != "ativa")

    paroquia.status = "ativa" if ativa else "inativa"
    paroquia.save(update_fields=["status"])

    msg = "Paróquia ativada" if ativa else "Paróquia desativada"

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
            return JsonResponse({"ok": False, "error": "status inválido"}, status=400)
        messages.error(request, "Status inválido.")
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
    return render(request, 'inscricoes/admin_geral_confirm_delete.html', {'obj': usuario, 'tipo': 'Usuário'})

def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


@login_required  # se preferir: @login_required(login_url="inscricoes:login")
def admin_paroquia_painel(request, paroquia_id: Optional[int] = None):
    """
    Painel da paróquia:
    - Admin da paróquia: sempre usa a paróquia vinculada ao usuário.
    - Admin geral: precisa informar paroquia_id (ex.: /painel/3/).
    - Outros: sem acesso.
    """
    user = request.user

    # --- Detecta papéis com fallback ---
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

    # --- Seleção da paróquia conforme papel ---
    if is_admin_paroquia:
        paroquia = getattr(user, "paroquia", None)
        if not paroquia:
            messages.error(request, "⚠️ Sua conta não está vinculada a uma paróquia.")
            return redirect("inscricoes:logout")

        # se tentarem acessar outra paróquia via URL, redireciona para a correta
        if paroquia_id and int(paroquia_id) != getattr(user, "paroquia_id", None):
            return redirect(reverse("inscricoes:admin_paroquia_painel"))

    elif is_admin_geral:
        if not paroquia_id:
            messages.error(request, "⚠️ Paróquia não especificada.")
            return redirect("inscricoes:admin_geral_list_paroquias")
        paroquia = get_object_or_404(Paroquia, id=paroquia_id)

    else:
        messages.error(request, "⚠️ Você não tem permissão para acessar este painel.")
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

    # Eventos abertos (detecção por múltiplos caminhos):
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
            total_inscricoes_confirmadas = 0  # sem referência

    # Pendentes = total - confirmadas (ignorando canceladas aqui)
    pendencias_contagem = max(total_inscricoes - total_inscricoes_confirmadas, 0)

    # =========================
    #   GRÁFICO: INSCRIÇÕES POR DIA (30 dias)
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

    # Gera e garante todos os dias (inclusive os sem inscrições) para linhas contínuas
    labels_dias = []
    values_dias = []
    dia_map = {row["dia"]: row["qtd"] for row in by_day} if by_day else {}
    for i in range(30):
        d = (start_30 + timedelta(days=i)).date()
        labels_dias.append(d.strftime("%d/%m"))
        values_dias.append(int(dia_map.get(d, 0)))

    # =========================
    #   GRÁFICO: INSCRIÇÕES POR EVENTO (apenas eventos "abertos", top 5)
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
    #   GRÁFICO: STATUS DE PAGAMENTO
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
    #   GRÁFICO: CONVERSÃO (inscritos x confirmados)
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

        # Séries/Gráficos (já como JSON seguro p/ template)
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
                messages.error(request, 'Selecione uma paróquia para o evento.')
                return render(request, 'inscricoes/evento_form.html', {'form': form})

            evento.save()
            messages.success(request, 'Evento criado com sucesso!')
            return redirect('inscricoes:admin_paroquia_painel')
    else:
        form = EventoForm(user=request.user)

    return render(request, 'inscricoes/evento_form.html', {'form': form})


@login_required
def eventos_listar(request):
    # sua lógica
    pass

@login_required
def inscricoes_listar(request):
    # código para listar inscrições
    pass

@login_required
@require_http_methods(["GET", "POST"])
def evento_editar(request, pk):
    """Editar evento (pk é UUID)."""
    evento = get_object_or_404(EventoAcampamento, pk=pk)

    # Permissão: admin da MESMA paróquia ou admin geral
    if not request.user.is_superuser:
        if not hasattr(request.user, "paroquia") or request.user.paroquia_id != evento.paroquia_id:
            return HttpResponseForbidden("Você não tem permissão para editar este evento.")

    if request.method == "POST":
        form = EventoForm(request.POST, request.FILES, instance=evento, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Evento atualizado com sucesso!")
            # redireciona para o painel da paróquia correta
            if hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral():
                return redirect("inscricoes:admin_paroquia_painel", paroquia_id=evento.paroquia_id)
            return redirect("inscricoes:admin_paroquia_painel")
    else:
        form = EventoForm(instance=evento, user=request.user)

    return render(request, "inscricoes/evento_form.html", {"form": form, "evento": evento})


@login_required
@require_http_methods(["GET", "POST"])
def evento_deletar(request, pk):
    """Confirma e deleta o evento (pk é UUID)."""
    evento = get_object_or_404(EventoAcampamento, pk=pk)

    # Permissão: admin da MESMA paróquia ou admin geral
    if not request.user.is_superuser:
        if not hasattr(request.user, "paroquia") or request.user.paroquia_id != evento.paroquia_id:
            return HttpResponseForbidden("Você não tem permissão para excluir este evento.")

    if request.method == "POST":
        nome = evento.nome
        paroquia_id = evento.paroquia_id
        evento.delete()
        messages.success(request, f"Evento “{nome}” excluído com sucesso.")

        # Volta para o painel apropriado
        if hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral():
            return redirect("inscricoes:admin_paroquia_painel", paroquia_id=paroquia_id)
        return redirect("inscricoes:admin_paroquia_painel")

    # GET: mostra a página de confirmação
    return render(request, "inscricoes/evento_confirm_delete.html", {"obj": evento, "tipo": "Evento"})


def inscricao_evento_publico(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # Aqui você pode colocar lógica para mostrar o formulário de inscrição, dados do evento, etc.
    context = {
        'evento': evento,
    }
    return render(request, 'inscricoes/evento_publico.html', context)

from .models import PoliticaPrivacidade


def ver_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)
    passos = [
        'Inscrição enviada',
        'Seleção do participante',
        'Pagamento confirmado',
        'Participação confirmada',
    ]

    if inscricao.inscricao_concluida:
        inscricao_status = 4
    elif inscricao.pagamento_confirmado:
        inscricao_status = 3
    elif inscricao.foi_selecionado:
        inscricao_status = 2
    else:
        inscricao_status = 1

    politica = PoliticaPrivacidade.objects.first()  # ou use get() se só houver uma

    return render(request, 'inscricoes/ver_inscricao.html', {
        'inscricao': inscricao,
        'passos': passos,
        'inscricao_status': inscricao_status,
        'evento': inscricao.evento,
        'politica': politica,
    })


from .forms import InscricaoForm
from .forms import ParticipanteForm
from django.forms import modelformset_factory

@login_required
def editar_inscricao(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)
    participante = inscricao.participante

    # Formulário por tipo de evento
    base_form_class = {
        'senior': InscricaoSeniorForm,
        'juvenil': InscricaoJuvenilForm,
        'mirim': InscricaoMirimForm,
        'servos': InscricaoServosForm,
    }.get(inscricao.evento.tipo)

    base_instance = None
    if base_form_class:
        base_model = base_form_class._meta.model
        base_instance = base_model.objects.filter(inscricao=inscricao).first()

    # Conjuge
    conjuge_instance = getattr(inscricao, 'conjuge', None)

    # Contatos
    ContatoFormSet = modelformset_factory(
    Contato,
    form=ContatoForm,
    fields='__all__',  # ou especifique os campos manualmente
    extra=0,
    can_delete=False
)

    contatos_queryset = Contato.objects.filter(inscricao=inscricao)

    # Pagamento
    pagamento_instance = Pagamento.objects.filter(inscricao=inscricao).first()

    if request.method == 'POST':
        inscricao_form = InscricaoForm(request.POST, instance=inscricao)
        participante_form = ParticipanteForm(request.POST, request.FILES, instance=participante)
        base_form = base_form_class(request.POST, instance=base_instance) if base_form_class else None
        conjuge_form = ConjugeForm(request.POST, instance=conjuge_instance) if conjuge_instance else None
        contato_forms = ContatoFormSet(request.POST, queryset=contatos_queryset)
        pagamento_form = PagamentoForm(request.POST, instance=pagamento_instance) if pagamento_instance else None

        if all([
            inscricao_form.is_valid(),
            participante_form.is_valid(),
            (base_form.is_valid() if base_form else True),
            (conjuge_form.is_valid() if conjuge_form else True),
            contato_forms.is_valid(),
            (pagamento_form.is_valid() if pagamento_form else True),
        ]):
            inscricao_form.save()
            participante_form.save()
            if base_form: base_form.save()
            if conjuge_form: conjuge_form.save()
            if pagamento_form: pagamento_form.save()
            for contato_form in contato_forms:
                contato_form.save()
            messages.success(request, "Inscrição atualizada com sucesso!")
            return redirect('inscricoes:ver_inscricao', pk=inscricao.pk)
    else:
        inscricao_form = InscricaoForm(instance=inscricao)
        participante_form = ParticipanteForm(instance=participante)
        base_form = base_form_class(instance=base_instance) if base_form_class else None
        conjuge_form = ConjugeForm(instance=conjuge_instance) if conjuge_instance else None
        contato_forms = ContatoFormSet(queryset=contatos_queryset)
        pagamento_form = PagamentoForm(instance=pagamento_instance) if pagamento_instance else None

    return render(request, 'inscricoes/editar_inscricao.html', {
        'inscricao': inscricao,
        'inscricao_form': inscricao_form,
        'participante_form': participante_form,
        'base_form': base_form,
        'conjuge_form': conjuge_form,
        'contato_forms': contato_forms,
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

    # tenta primeiro a relação "preferida" pelo tipo do evento; depois faz fallback em todas
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

    # Data de nascimento (com fallback no Participante, se existir lá)
    data_nascimento = getattr(base, 'data_nascimento', None) or getattr(inscricao.participante, 'data_nascimento', None)

    return render(request, 'inscricoes/ficha_inscricao.html', {
        'inscricao': inscricao,
        'inscricao_base': base,           # pode ser None se ainda não preencheram a ficha
        'data_nascimento': data_nascimento,
    })


@login_required
def imprimir_cracha(request, pk):
    inscricao = get_object_or_404(Inscricao, pk=pk)
    # Aqui você pode gerar PDF ou página para impressão do crachá
    return render(request, 'inscricoes/imprimir_cracha.html', {'inscricao': inscricao})

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

        # Validação valor
        if not valor:
            erros.append('O valor é obrigatório.')
        else:
            try:
                valor_decimal = float(valor)
                if valor_decimal <= 0:
                    erros.append('O valor deve ser maior que zero.')
            except ValueError:
                erros.append('Valor inválido.')

        # Validação método
        if metodo not in [choice[0] for choice in metodo_choices]:
            erros.append('Método de pagamento inválido.')

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
            # Se enviou comprovante, salva no campo (substitui se já tinha)
            if comprovante:
                pagamento.comprovante = comprovante
                pagamento.save()

            # Marca a inscrição como pagamento confirmado
            if not inscricao.pagamento_confirmado:
                inscricao.pagamento_confirmado = True
                inscricao.save()

            messages.success(request, 'Pagamento incluído com sucesso!')
            return redirect('inscricoes:evento_participantes', evento_id=inscricao.evento.id)

    else:
        # GET: tenta carregar pagamento existente para preencher formulário
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

    # Usa o tipo efetivo (pode “virar” casais quando servos vinculado a casais)
    tipo_eff = _tipo_formulario_evento(evento)
    is_casais = (tipo_eff == 'casais')

    # Fora do período?
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
                erros.append("Informe um CPF válido (11 dígitos) para o 1º participante.")
            if cpf2 and len(cpf2) != 11:
                erros.append("Informe um CPF válido (11 dígitos) para o 2º participante.")
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
                    'metodo': Pagamento.MetodoPagamento.PIX,  # ajuste se necessário
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

            messages.success(request, "Inscrição(ões) criada(s) e pagamento(s) marcado(s) como pendente(s).")
            return redirect('inscricoes:ver_inscricao', pk=i1.id)

        # GET ou inválido
        return render(request, 'inscricoes/form_basico_pagamento.html', {
            'form': form, 'evento': evento, 'politica': politica
        })
    # =================== FIM FLUXO "PAGAMENTO" =================== #

    # Para 'casais' (inclusive servos->casais)
    if is_casais:
        return redirect('inscricoes:formulario_casais', evento_id=evento.id)

    # --- Retomar endereço ---
    if request.GET.get("retomar") == "1" and request.GET.get("pid"):
        try:
            participante_id = int(request.GET["pid"])
            participante = Participante.objects.get(id=participante_id)
            Inscricao.objects.get(participante=participante, evento=evento)
            request.session["participante_id"] = participante.id
        except (ValueError, Participante.DoesNotExist, Inscricao.DoesNotExist):
            pass

    # --- Etapa endereço ---
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

    # --- Etapa inicial padrão ---
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

    # tenta achar participante por CPF em ambas formas (com/sem máscara)
    possiveis_cpfs = {_fmt_cpf(cpf), cpf}

    p = Participante.objects.filter(cpf__in=possiveis_cpfs).first()
    if not p:
        # não tem cadastro ainda — ok (não bloqueia)
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

    # Tenta achar a inscrição deste evento
    inscricao = None
    if evento_id:
        inscricao = Inscricao.objects.filter(participante=participante, evento_id=evento_id).first()

    # Se NÃO tem inscrição neste evento → devolve dados p/ autopreencher
    if not inscricao:
        return JsonResponse({
            'ja_inscrito': False,          # compat com front antigo
            'existe_participante': True,
            'status': 'sem_inscricao',
            'nome': participante.nome or '',
            'email': participante.email or '',
            'telefone': participante.telefone or '',
        })

    # Já existe inscrição — calcular próxima etapa
    prog = _proxima_etapa_forms(inscricao)
    payload = {
        'ja_inscrito': inscricao.inscricao_enviada,  # compat: só "True" quando já enviada
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
    # Obtém a inscrição, evento e política de privacidade
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    politica = PoliticaPrivacidade.objects.first()

    # Mapeia tipo de evento → (FormClass, atributo OneToOne na Inscricao)
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
        raise Http404("Tipo de evento inválido.")

    FormClass, rel_name = form_map[tipo_eff]
    instancia = getattr(inscricao, rel_name, None)
    conj_inst = getattr(inscricao, 'conjuge', None)  # pode existir de eventos casais

    if request.method == 'POST':
        form = FormClass(request.POST, request.FILES, instance=instancia)
        conj_form = ConjugeForm(request.POST, instance=conj_inst) if tipo_eff == "casais" else None

        # validação: cônjuge só é obrigatório para casais
        if form.is_valid() and (tipo_eff != "casais" or (conj_form and conj_form.is_valid())):
            # Salva dados do formulário principal
            obj = form.save(commit=False)
            obj.inscricao = inscricao
            obj.paroquia = inscricao.paroquia  # se seu modelo possui campo paroquia
            obj.save()

            # Salva dados do Cônjuge (apenas para 'casais' efetivo)
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

        # Cônjuge (apenas quando casais efetivo)
        'nome_conjuge',
        'conjuge_inscrito',
        'ja_e_campista_conjuge',
        'tema_acampamento_conjuge',

        # Casado/união estável
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

    # Só faz sentido no PRINCIPAL (não no próprio evento de servos)
    if (ev.tipo or "").lower() == "servos":
        return JsonResponse({"ok": False, "msg": "Ação permitida apenas no evento principal."}, status=400)

    permitir = (request.POST.get("permitir") or "").lower() in ("1", "true", "on", "yes", "sim")
    ev.permitir_inscricao_servos = permitir
    ev.save(update_fields=["permitir_inscricao_servos"])

    msg = "Inscrições de servos ativadas." if permitir else "Inscrições de servos desativadas."
    return JsonResponse({"ok": True, "permitir": permitir, "msg": msg})


from django.forms import modelformset_factory
from .models import Filho
from .forms import ContatoForm, FilhoForm

from django.shortcuts import render, get_object_or_404, redirect
from django.forms import modelformset_factory
from .models import Inscricao, PoliticaPrivacidade, Filho
from .forms import ContatoForm, FilhoForm


def formulario_contato(request, inscricao_id):
    # Recupera a inscrição
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Evento e política
    evento = inscricao.evento
    politica = PoliticaPrivacidade.objects.first()

    # Só cria formset de filhos se for evento de casais
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
            # Atualiza os dados da inscrição
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
        # Pré-popula formulário
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
        'filhos_formset': filhos_formset,  # pode ser None se não for casais
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

    # Mapeia tipo → modelo correto da BaseInscricao (inclui novos tipos)
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
        raise Http404("Tipo de evento inválido.")

    # Garante que a base exista (evita 404 quando ainda não foi criada)
    base_inscricao, _ = Model.objects.get_or_create(
        inscricao=inscricao,
        defaults={'paroquia': inscricao.paroquia}
    )

    # Cria um ModelForm dinâmico reusando seu DadosSaudeForm (mesmos campos/validações)
    SaudeForm = modelform_factory(
        Model,
        form=DadosSaudeForm,
        fields=DadosSaudeForm.Meta.fields
    )

    if request.method == 'POST':
        form_saude = SaudeForm(request.POST, request.FILES, instance=base_inscricao)

        # Decisão do modal de consentimento (input hidden no template)
        consent_ok = (request.POST.get('consentimento_envio') == 'sim')
        if not consent_ok:
            form_saude.add_error(None, "Você precisa aceitar a Política de Privacidade para enviar a inscrição.")

        if form_saude.is_valid():
            # Salva os campos do modelo (a 'foto' é extra de formulário)
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

            # Marca inscrição como enviada (disparos automáticos ficam no save do modelo)
            if not inscricao.inscricao_enviada:
                inscricao.inscricao_enviada = True
                inscricao.save(update_fields=['inscricao_enviada'])

            messages.success(request, "Dados de saúde enviados com sucesso.")
            return redirect('inscricoes:ver_inscricao', pk=inscricao.id)
        else:
            # Debug opcional
            print("Erros no DadosSaudeForm:", form_saude.errors)
    else:
        # GET: carrega com dados já salvos
        form_saude = SaudeForm(instance=base_inscricao)

    return render(request, 'inscricoes/formulario_saude.html', {
        'form': form_saude,
        'inscricao': inscricao,
        'evento': evento,
        'politica': politica,
    })



def preencher_dados_contato(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    participante = inscricao.participante  # Associe ao participante da inscrição

    if request.method == 'POST':
        form = ContatoForm(request.POST)
        if form.is_valid():
            contato = form.save(commit=False)
            contato.participante = participante  # Associa ao participante
            contato.save()

            # Redireciona para a etapa final (dados de saúde ou página de sucesso)
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

@login_required
def relatorio_crachas(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    cidade_selecionada = (request.GET.get('cidade') or '').strip()

    # Base: somente inscrições concluídas
    qs_base = (Inscricao.objects
               .filter(evento=evento, inscricao_concluida=True)
               .select_related(
                   'participante', 'paroquia',
                   'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
                   'inscricaocasais', 'inscricaoevento', 'inscricaoretiro',
               ))

    # Cidades (sempre com base no conjunto completo concluído do evento)
    cidades = (qs_base.values_list('participante__cidade', flat=True)
                     .distinct()
                     .order_by('participante__cidade'))

    # Filtro por cidade (case-insensitive)
    if cidade_selecionada:
        qs = qs_base.filter(participante__cidade__iexact=cidade_selecionada)
    else:
        qs = qs_base

    # Ordenação por nome do participante
    qs = qs.order_by('participante__nome')

    # Resolve data de nascimento uma única vez e pendura na inscrição (opcional)
    attr_by_tipo = {
        'senior':  'inscricaosenior',
        'juvenil': 'inscricaojuvenil',
        'mirim':   'inscricaomirim',
        'servos':  'inscricaoservos',
        'casais':  'inscricaocasais',
        'evento':  'inscricaoevento',
        'retiro':  'inscricaoretiro',
    }

    def get_base_rel(i):
        tipo = (getattr(i.evento, 'tipo', '') or '').lower()
        preferida = attr_by_tipo.get(tipo)
        ordem = [preferida] if preferida else []
        ordem += ['inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
                  'inscricaocasais', 'inscricaoevento', 'inscricaoretiro']
        seen = set()
        for name in [n for n in ordem if n and n not in seen]:
            seen.add(name)
            try:
                return getattr(i, name)
            except Exception:
                continue
        return None

    inscricoes = []
    for insc in qs:
        base = get_base_rel(insc)
        nasc = getattr(base, 'data_nascimento', None) if base else None
        if not nasc and hasattr(insc.participante, 'data_nascimento'):
            nasc = insc.participante.data_nascimento
        insc.nasc = nasc  # disponível no template se quiser usar {{ inscricao.nasc|date:"d/m/Y" }}
        inscricoes.append(insc)

    # Template de crachá (se tiver por evento, adapte aqui)
    cracha_template = CrachaTemplate.objects.first()

    return render(request, 'inscricoes/relatorio_crachas.html', {
        'evento': evento,
        'inscricoes': inscricoes,
        'cidades': cidades,
        'cidade_selecionada': cidade_selecionada,
        'cracha_template': cracha_template,
    })

def relatorio_fichas_sorteio(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    cidade = request.GET.get("cidade")

    # só inscrições concluídas
    inscricoes = Inscricao.objects.filter(
        evento=evento,
        inscricao_concluida=True
    )

    # filtra por cidade da paroquia
    if cidade:
        inscricoes = inscricoes.filter(paroquia__cidade=cidade)

    # lista de cidades para o <select>
    cidades = inscricoes.values_list('paroquia__cidade', flat=True).distinct().order_by('paroquia__cidade')

    return render(request, 'inscricoes/relatorio_fichas_sorteio.html', {
        'evento': evento,
        'inscricoes': inscricoes,           # agora iteramos nas Inscricoes
        'cidades': cidades,
        'cidade_selecionada': cidade,
    })

@login_required
def relatorio_inscritos(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    cidade_filtro      = request.GET.get('cidade', '')
    status_filtro      = request.GET.get('status', '')
    selecionado_filtro = request.GET.get('selecionado', '')

    # 1) Inscrições do evento
    inscricoes = Inscricao.objects.filter(evento=evento)

    # 2) Filtros
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

    # 3) Participantes e cidades
    participantes = Participante.objects.filter(inscricao__in=inscricoes).distinct()
    cidades = participantes.values_list('cidade', flat=True).distinct().order_by('cidade')

    # 4) Carrega todas as possíveis OneToOne para evitar N+1
    inscricoes_qs = (
        inscricoes
        .select_related(
            'participante',
            'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos',
            'inscricaocasais', 'inscricaoevento', 'inscricaoretiro'
        )
    )

    # Mapeia o tipo do evento para o nome da relação OneToOne
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
        Retorna o objeto BaseInscricao do tipo CORRETO conforme i.evento.tipo.
        Se não existir, tenta fallback nas outras relações, sem quebrar.
        """
        nomes = []
        tipo = (getattr(i.evento, 'tipo', '') or '').lower()
        preferida = attr_by_tipo.get(tipo)
        if preferida:
            nomes.append(preferida)
        # fallback: percorre todas (cobre dados antigos/inconsistências)
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

    # 5) Prepara dados prontos para o template
    inscricoes_dict = {}
    for i in inscricoes_qs:
        rel = get_base_rel(i)
        camisa = (getattr(rel, 'tamanho_camisa', '') or '').upper()
        nasc   = getattr(rel, 'data_nascimento', None)

        # (Opcional) fallback: se você guardar data no Participante
        if not nasc and hasattr(i.participante, 'data_nascimento'):
            nasc = i.participante.data_nascimento

        # >>>>>>>  MUDE AQUI: sem underscore  <<<<<<<
        i.camisa = camisa
        i.nasc   = nasc
        inscricoes_dict[i.participante_id] = i

    # 6) Contagem por tamanho — usa as choices do seu modelo (inclui XGG)
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
        'participantes': participantes,
        'cidades': cidades,
        'inscricoes_dict': inscricoes_dict,
        'cidade_filtro': cidade_filtro,
        'status_filtro': status_filtro,
        'selecionado_filtro': selecionado_filtro,
        'quantidades_camisas': quantidades_camisas,
        'now': timezone.now(),
    })



# Relatório Financeiro
def relatorio_financeiro(request, evento_id):
    evento = get_object_or_404(evento, id=evento_id)
    participantes = Participante.objects.filter(inscricao__evento=evento)
    # Em versão futura, pode incluir valores pagos, totais, etc.
    return render(request, 'relatorios/relatorio_financeiro.html', {
        'evento': evento,
        'participantes': participantes
    })

def pagina_video_evento(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # o vídeo está em evento.video.arquivo, se existir
    video = getattr(evento, 'video', None)
    return render(request, 'inscricoes/video_evento.html', {
        'evento': evento,
        'video': video,
    })

def alterar_politica(request):
    politica = PoliticaPrivacidade.objects.first()  # Pega a primeira (e única) política
    if not politica:
        politica = PoliticaPrivacidade.objects.create() # Cria se não existir

    if request.method == 'POST':
        form = PoliticaPrivacidadeForm(request.POST, request.FILES, instance=politica)
        if form.is_valid():
            form.save()
            return redirect('inscricoes:admin_geral_dashboard')  # Redireciona para o dashboard após salvar
    else:
        form = PoliticaPrivacidadeForm(instance=politica)

    return render(request, 'inscricoes/alterar_politica.html', {'form': form})

def relatorio_financeiro(request, evento_id):
    """
    Gera um relatório financeiro detalhado para um evento específico.
    """
    evento = EventoAcampamento.objects.get(pk=evento_id)

    # Calcula o total arrecadado por método de pagamento
    total_pix = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO,
        metodo=Pagamento.MetodoPagamento.PIX
    ).aggregate(total=Sum('valor'))['total'] or 0

    total_credito = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO,
        metodo=Pagamento.MetodoPagamento.CREDITO
    ).aggregate(total=Sum('valor'))['total'] or 0

    total_debito = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO,
        metodo=Pagamento.MetodoPagamento.DEBITO
    ).aggregate(total=Sum('valor'))['total'] or 0

    total_dinheiro = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO,
        metodo=Pagamento.MetodoPagamento.DINHEIRO
    ).aggregate(total=Sum('valor'))['total'] or 0

    # Calcula o total arrecadado com pagamentos confirmados
    total_arrecadado = total_pix + total_credito + total_debito + total_dinheiro

    # Calcula o total esperado (valor das inscrições * número de inscritos)
    total_esperado = evento.valor_inscricao * Inscricao.objects.filter(evento=evento).count()

    # Calcula o total pendente
    total_pendente = total_esperado - total_arrecadado

    # Recupera os pagamentos confirmados para detalhamento
    pagamentos_confirmados = Pagamento.objects.filter(
        inscricao__evento=evento,
        status=Pagamento.StatusPagamento.CONFIRMADO
    )

    context = {
        'evento': evento,
        'total_arrecadado': total_arrecadado,
        'total_esperado': total_esperado,
        'total_pendente': total_pendente,
        'pagamentos_confirmados': pagamentos_confirmados,
        'total_pix': total_pix,
        'total_credito': total_credito,
        'total_debito': total_debito,
        'total_dinheiro': total_dinheiro,
    }

    return render(request, 'inscricoes/relatorio_financeiro.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def ver_logs_bruto(request):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'usuarios.log')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            linhas = f.readlines()[-200:]
    else:
        linhas = ["Arquivo de log não encontrado."]
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
        eventos.append({'tipo': 'erro', 'mensagem': 'Arquivo de log não encontrado.'})

    return render(request, 'logs/ver_logs_lista.html', {'eventos': eventos})

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def download_logs(request):
    log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'usuarios.log')
    if os.path.exists(log_path):
        return FileResponse(open(log_path, 'rb'), as_attachment=True, filename='usuarios.log')
    else:
        return HttpResponse("Arquivo de log não encontrado.", status=404)
    
@require_GET
def pagina_video_evento(request, slug):
    evento = get_object_or_404(EventoAcampamento, slug=slug)
    # Se houver relação OneToOne chamada "video"
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
            messages.success(request, '✅ Pastoral/Movimento cadastrado com sucesso!')
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
        messages.error(request, "Seu usuário não está vinculado a uma paróquia.")
        return redirect("inscricoes:admin_paroquia_painel")

    config, _ = MercadoPagoConfig.objects.get_or_create(paroquia=paroquia)

    if request.method == "POST":
        form = MercadoPagoConfigForm(request.POST, instance=config)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.paroquia = paroquia  # garante vínculo correto
            obj.save()
            messages.success(request, "Configuração do Mercado Pago salva com sucesso!")
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
        raise ValueError("Mercado Pago não configurado para esta paróquia.")
    return mercadopago.SDK(cfg.access_token.strip())

def _sincronizar_pagamento(mp_client, inscricao, payment_id):
    """
    Busca o pagamento no MP, garante que o external_reference bate com a inscrição
    e sincroniza o registro OneToOne Pagamento dessa inscrição.
    """
    payment = mp_client.payment().get(payment_id)["response"]

    # Segurança: confere vínculo
    if str(payment.get("external_reference")) != str(inscricao.id):
        raise ValueError("Pagamento não corresponde à inscrição.")

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


# ===== Iniciar pagamento =====================================================

def iniciar_pagamento(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Regras de negócio
    if not inscricao.foi_selecionado:
        messages.error(request, "Inscrição ainda não selecionada. Aguarde a seleção para pagar.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

    if inscricao.pagamento_confirmado:
        messages.info(request, "Pagamento já confirmado para esta inscrição.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

    # Config da Paróquia
    try:
        config = inscricao.paroquia.mp_config
    except MercadoPagoConfig.DoesNotExist:
        messages.error(request, "Pagamento não configurado para esta paróquia.")
        return redirect("inscricoes:pagina_de_contato")

    access_token = (config.access_token or "").strip()
    if not access_token:
        messages.error(request, "Pagamento não configurado. Entre em contato com a organização.")
        return redirect("inscricoes:pagina_de_contato")

    sdk = mercadopago.SDK(access_token)

    # URLs baseadas no request (local)…
    sucesso_url = request.build_absolute_uri(reverse("inscricoes:mp_success", args=[inscricao.id]))
    falha_url   = request.build_absolute_uri(reverse("inscricoes:mp_failure", args=[inscricao.id]))
    pend_url    = request.build_absolute_uri(reverse("inscricoes:mp_pending", args=[inscricao.id]))
    webhook_url = request.build_absolute_uri(reverse("inscricoes:mp_webhook"))

    # …mas se você tiver um domínio público HTTPS em settings.SITE_DOMAIN, usa ele.
    site_domain = (getattr(settings, "SITE_DOMAIN", "") or "").rstrip("/")
    if site_domain.startswith("https://"):
        sucesso_url = urljoin(site_domain, reverse("inscricoes:mp_success", args=[inscricao.id]))
        falha_url   = urljoin(site_domain, reverse("inscricoes:mp_failure", args=[inscricao.id]))
        pend_url    = urljoin(site_domain, reverse("inscricoes:mp_pending", args=[inscricao.id]))
        webhook_url = urljoin(site_domain, reverse("inscricoes:mp_webhook"))

    pref_data = {
        "items": [{
            "title": f"Inscrição – {inscricao.evento.nome}"[:60],
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

    # Só adiciona auto_return se o success for HTTPS (exigência do MP)
    if sucesso_url.startswith("https://"):
        pref_data["auto_return"] = "approved"

    try:
        mp_pref = sdk.preference().create(pref_data)
        resp = mp_pref.get("response", {}) or {}
        logging.info("MP Preference response: %r", resp)

        # Erros comuns do MP (status 400 / message / error)
        if resp.get("status") == 400 or resp.get("error") or resp.get("message"):
            msg = resp.get("message") or "Falha ao criar preferência no Mercado Pago."
            if settings.DEBUG:
                return HttpResponse(f"<h3>Erro do MP</h3><pre>{resp}</pre>", content_type="text/html")
            messages.error(request, msg)
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        init_point = resp.get("init_point") or resp.get("sandbox_init_point")
        if not init_point:
            if settings.DEBUG:
                return HttpResponse("<h3>Preferência sem init_point</h3><pre>%s</pre>" % resp, content_type="text/html")
            messages.error(request, "Preferência criada sem link de checkout. Tente novamente.")
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
                "metodo": Pagamento.MetodoPagamento.PIX,  # o método real vem no webhook
            },
        )

        return redirect(init_point)

    except Exception as e:
        logging.exception("Erro ao criar preferência do Mercado Pago: %s", e)
        if settings.DEBUG:
            return HttpResponse(f"<h3>Exceção ao criar preferência</h3><pre>{e}</pre>", content_type="text/html")
        messages.error(request, "Erro ao iniciar pagamento. Tente novamente mais tarde.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)

# ===== Páginas de retorno (UX) ==============================================

@require_GET
def mp_success(request, inscricao_id):
    """Usuário voltou do Checkout com status success. Validamos no servidor e mostramos confirmação."""
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    payment_id = request.GET.get("payment_id")

    if payment_id:
        try:
            mp = _mp_client_by_paroquia(inscricao.paroquia)
            _sincronizar_pagamento(mp, inscricao, payment_id)
        except Exception as e:
            logging.exception("Erro ao validar sucesso MP: %s", e)
            messages.warning(request, "Pagamento recebido. Aguardando confirmação final do provedor.")
            # Cai para a página de sucesso mesmo assim (UX), mas status pode ficar pendente até o webhook.

    return render(request, "pagamentos/sucesso.html", {"inscricao": inscricao})


@require_GET
def mp_pending(request, inscricao_id):
    """Pagamento pendente/análise (PIX/boleto, cartão em análise)."""
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    return render(request, "pagamentos/pendente.html", {"inscricao": inscricao})


@require_GET
def mp_failure(request, inscricao_id):
    """Falha/cancelamento. Incentiva tentar novamente."""
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    messages.error(request, "Pagamento não foi concluído. Você pode tentar novamente.")
    return render(request, "pagamentos/falhou.html", {"inscricao": inscricao})


# ===== Webhook (fonte da verdade) ===========================================

@require_POST
@csrf_exempt
def mp_webhook(request):
    """
    Produção: consulta pagamento na API do MP e sincroniza por external_reference.
    DEBUG: se payload trouxer 'test': {'inscricao_id': ..., 'status': ...},
           atualiza direto sem chamar o MP.
    """
    try:
        payload = json.loads(request.body or "{}")

        # ------- ATALHO DE TESTE LOCAL (somente em DEBUG) -------
        if settings.DEBUG:
            test = payload.get("test")
            if isinstance(test, dict) and test.get("inscricao_id"):
                inscricao = get_object_or_404(Inscricao, id=test["inscricao_id"])
                status = (test.get("status") or "approved").lower()

                # Atualiza/garante Pagamento OneToOne
                pagamento, _ = Pagamento.objects.get_or_create(
                    inscricao=inscricao,
                    defaults={"valor": inscricao.evento.valor_inscricao}
                )

                if status in ("approved", "confirmado"):
                    pagamento.status = Pagamento.StatusPagamento.CONFIRMADO
                    inscricao.pagamento_confirmado = True
                    inscricao.inscricao_concluida = True
                    inscricao.save(update_fields=["pagamento_confirmado", "inscricao_concluida"])
                elif status in ("pending", "in_process", "pendente"):
                    pagamento.status = Pagamento.StatusPagamento.PENDENTE
                else:
                    pagamento.status = Pagamento.StatusPagamento.CANCELADO

                pagamento.transacao_id = str(payload.get("data", {}).get("id") or "TESTE_LOCAL")
                pagamento.save()
                logging.info("Webhook DEBUG aplicado para inscrição %s com status %s", inscricao.id, status)
                return HttpResponse(status=200)
        # --------------------------------------------------------

        # Fluxo normal (produção): extrai payment_id e descobre external_reference
        payment_id = (payload.get("data") or {}).get("id") or payload.get("id")
        if not payment_id:
            logging.warning("Webhook sem payment_id: %s", payload)
            return HttpResponse(status=200)

        # 1ª consulta (qualquer token) só para descobrir external_reference
        cfg_any = MercadoPagoConfig.objects.first()
        if not cfg_any or not cfg_any.access_token:
            logging.error("Nenhuma configuração do MP encontrada.")
            return HttpResponse(status=200)

        mp_any = mercadopago.SDK(cfg_any.access_token.strip())
        payment_tmp = mp_any.payment().get(payment_id).get("response", {})
        inscricao_id = payment_tmp.get("external_reference")
        if not inscricao_id:
            logging.error("Pagamento %s sem external_reference.", payment_id)
            return HttpResponse(status=200)

        inscricao = get_object_or_404(Inscricao, id=inscricao_id)

        # Reconsulta com a credencial da paróquia correta e sincroniza
        mp = _mp_client_by_paroquia(inscricao.paroquia)
        _sincronizar_pagamento(mp, inscricao, payment_id)

        logging.info("Webhook OK para pagamento %s (inscrição %s)", payment_id, inscricao_id)
        return HttpResponse(status=200)

    except Exception as e:
        logging.exception("Erro ao processar webhook MP: %s", e)
        return HttpResponse(status=200)  # evita reentrega infinita


# ===== Página de contato (sem alterações lógicas) ===========================

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
def relatorios_evento(request, evento_id):
    # Busca o evento
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # Opcional: só permite que admin da paróquia ou superuser acesse
    if not request.user.is_superuser:
        if not hasattr(request.user, 'paroquia') or evento.paroquia != request.user.paroquia:
            return HttpResponseForbidden("Você não tem permissão para ver estes relatórios.")

    # Renderiza uma página com todos os botões de relatório
    return render(request, 'inscricoes/relatorios_evento.html', {
        'evento': evento
    })

@login_required
def relatorio_etiquetas_bagagem(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    # Permissão: superuser ou mesma paróquia
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    # Filtro por cidade (query param ?cidade=…)
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

    # Monta lista de etiquetas (3 por inscrição)
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
    Retorna a BaseInscricao (InscricaoSenior/Juvenil/Mirim/Servos) ligada à inscrição.
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

@login_required
def relatorio_ficha_cozinha(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # Permissão: igual ao seu exemplo (superuser OU mesma paróquia do evento)
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    # Filtro por cidade (opcional via GET)
    cidade_sel = (request.GET.get('cidade') or '').strip()

    # Para performance, filtramos direto na tabela do subtipo conforme o tipo do evento
    tipo = evento.tipo
    if tipo == 'senior':
        base_qs = (InscricaoSenior.objects
                   .filter(inscricao__evento=evento,
                           inscricao__pagamento_confirmado=True,
                           alergia_alimento__iexact='sim')
                   .select_related('inscricao__participante'))
    elif tipo == 'juvenil':
        base_qs = (InscricaoJuvenil.objects
                   .filter(inscricao__evento=evento,
                           inscricao__pagamento_confirmado=True,
                           alergia_alimento__iexact='sim')
                   .select_related('inscricao__participante'))
    elif tipo == 'mirim':
        base_qs = (InscricaoMirim.objects
                   .filter(inscricao__evento=evento,
                           inscricao__pagamento_confirmado=True,
                           alergia_alimento__iexact='sim')
                   .select_related('inscricao__participante'))
    else:
        base_qs = (InscricaoServos.objects
                   .filter(inscricao__evento=evento,
                           inscricao__pagamento_confirmado=True,
                           alergia_alimento__iexact='sim')
                   .select_related('inscricao__participante'))

    if cidade_sel:
        base_qs = base_qs.filter(inscricao__participante__cidade=cidade_sel)

    # Monta estrutura esperada pelo template: [{'inscricao': ..., 'base': ...}, ...]
    fichas = [{'inscricao': b.inscricao, 'base': b} for b in base_qs]

    # Opções de cidades (derivadas do conjunto já filtrado por pagamento + alergia)
    cidades = (base_qs
               .values_list('inscricao__participante__cidade', flat=True)
               .distinct()
               .order_by('inscricao__participante__cidade'))

    return render(request, 'inscricoes/ficha_cozinha.html', {
        'evento': evento,
        'fichas': fichas,        # somente pagos + com alergia a alimento
        'cidades': cidades,
        'cidade_sel': cidade_sel,
    })

@login_required
def relatorio_ficha_farmacia(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()

    # Busca inscrições com pagamento confirmado
    inscricoes = Inscricao.objects.filter(
        evento=evento,
        pagamento_confirmado=True
    ).select_related('participante')

    fichas = []
    for inscr in inscricoes:
        # escolhe o BaseInscricao certo
        tipo = evento.tipo
        if tipo == 'senior':
            base = InscricaoSenior.objects.filter(inscricao=inscr).first()
        elif tipo == 'juvenil':
            base = InscricaoJuvenil.objects.filter(inscricao=inscr).first()
        elif tipo == 'mirim':
            base = InscricaoMirim.objects.filter(inscricao=inscr).first()
        else:
            base = InscricaoServos.objects.filter(inscricao=inscr).first()

        if not base:
            continue

        # só inclui quem tem **algum** dado de saúde relevante
        tem_saude = any([
            base.problema_saude == 'sim',
            base.medicamento_controlado == 'sim',
            base.mobilidade_reduzida == 'sim',
            getattr(base, 'alergia_alimento', '') == 'sim',
            getattr(base, 'alergia_medicamento', '') == 'sim',
            bool(base.informacoes_extras),
        ])
        if not tem_saude:
            continue

        fichas.append({'inscricao': inscr, 'base': base})

    # filtro por cidade
    cidades = sorted({f['inscricao'].participante.cidade for f in fichas})
    cidade_sel = request.GET.get('cidade')
    if cidade_sel:
        fichas = [f for f in fichas if f['inscricao'].participante.cidade == cidade_sel]

    return render(request, 'inscricoes/ficha_farmacia.html', {
        'evento': evento,
        'fichas': fichas,
        'cidades': cidades,
        'cidade_sel': cidade_sel,
    })

def qr_code_png(request, token):
    """
    Gera um PNG de QR code que aponta para a página de inscrição
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

# views.py (adicione abaixo das suas imports já corrigidas)

def aguardando_pagamento(request, inscricao_id):
    """
    Cria a preferência no MP e mostra uma página 'Aguardando pagamento'.
    A página abre o Checkout em nova aba e começa a fazer polling no backend.
    """
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Regras
    if not inscricao.foi_selecionado:
        messages.error(request, "Inscrição ainda não selecionada.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)
    if inscricao.pagamento_confirmado:
        return redirect("inscricoes:mp_success", inscricao.id)

    # Config MP
    try:
        cfg = inscricao.paroquia.mp_config
    except MercadoPagoConfig.DoesNotExist:
        messages.error(request, "Pagamento não configurado.")
        return redirect("inscricoes:pagina_de_contato")

    access_token = (cfg.access_token or "").strip()
    if not access_token:
        messages.error(request, "Pagamento não configurado.")
        return redirect("inscricoes:pagina_de_contato")

    sdk = mercadopago.SDK(access_token)

    # URLs absolutas no seu domínio
    sucesso_url = request.build_absolute_uri(reverse("inscricoes:mp_success", args=[inscricao.id]))
    falha_url   = request.build_absolute_uri(reverse("inscricoes:mp_failure", args=[inscricao.id]))
    pend_url    = request.build_absolute_uri(reverse("inscricoes:mp_pending", args=[inscricao.id]))
    # notification_url precisa ser público e HTTPS
    webhook_url = request.build_absolute_uri(reverse("inscricoes:mp_webhook"))

    pref_data = {
        "items": [{
            "title": f"Inscrição – {inscricao.evento.nome}"[:60],
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": float(inscricao.evento.valor_inscricao),
        }],
        "payer": {"email": inscricao.participante.email},
        "external_reference": str(inscricao.id),
        "back_urls": {"success": sucesso_url, "failure": falha_url, "pending": pend_url},
        "auto_return": "approved",               # só cartão aprovado redireciona
        "notification_url": webhook_url,        # webhook é a 'fonte da verdade'
    }

    try:
        mp_pref = sdk.preference().create(pref_data)
        resp = mp_pref.get("response", {}) or {}
        if resp.get("status") == 400 or resp.get("error") or resp.get("message"):
            msg = resp.get("message") or "Falha ao criar preferência no Mercado Pago."
            if settings.DEBUG:
                return HttpResponse(f"<pre>{resp}</pre>", content_type="text/html")
            messages.error(request, msg)
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        init_point = resp.get("init_point") or resp.get("sandbox_init_point")
        if not init_point:
            messages.error(request, "Preferência criada sem link de checkout.")
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

        # Renderiza página que abre o MP em nova aba e faz polling
        return render(request, "pagamentos/aguardando.html", {
            "inscricao": inscricao,
            "init_point": init_point,
        })
    except Exception as e:
        logging.exception("Erro ao criar preferência MP: %s", e)
        if settings.DEBUG:
            return HttpResponse(f"<pre>{e}</pre>", content_type="text/html")
        messages.error(request, "Erro ao iniciar pagamento.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)


@require_GET
def status_pagamento(request, inscricao_id):
    """
    API simples para o polling no front.
    Retorna o status atual do Pagamento da inscrição.
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

def iniciar_pagamento_pix(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Regras de negócio
    if not inscricao.foi_selecionado:
        messages.error(request, "Inscrição ainda não selecionada.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)
    if inscricao.pagamento_confirmado:
        return redirect("inscricoes:mp_success", inscricao.id)

    # Credenciais da paróquia
    try:
        cfg = inscricao.paroquia.mp_config
    except MercadoPagoConfig.DoesNotExist:
        messages.error(request, "Pagamento não configurado para esta paróquia.")
        return redirect("inscricoes:pagina_de_contato")

    access_token = (cfg.access_token or "").strip()
    if not access_token:
        messages.error(request, "Pagamento não configurado.")
        return redirect("inscricoes:pagina_de_contato")

    mp = mercadopago.SDK(access_token)

    # URL absoluta e pública (HTTPS) para o webhook
    base = (getattr(settings, "SITE_URL", "") or "https://eismeaqui.app.br").rstrip("/") + "/"
    notification_url = urljoin(base, reverse("inscricoes:mp_webhook").lstrip("/"))

    # Expiração em 30 min — exigido pelo MP: YYYY-MM-DDTHH:MM:SS.000Z (UTC)
    expires_at = (dj_tz.now().astimezone(dt_tz.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    body = {
        "transaction_amount": float(inscricao.evento.valor_inscricao),
        "description": f"Inscrição – {inscricao.evento.nome}"[:60],
        "payment_method_id": "pix",
        "payer": {"email": inscricao.participante.email or "sem-email@example.com"},
        "external_reference": str(inscricao.id),
        "notification_url": notification_url,
        "date_of_expiration": expires_at,
    }

    try:
        resp = mp.payment().create(body)
        data = resp.get("response", {}) or {}
        logging.info("PIX create response: %r", data)

        # Erro da API
        if data.get("status") == 400 or data.get("error"):
            msg = data.get("message") or "Falha ao criar pagamento PIX."
            logging.error("PIX_FAIL: %s | %r", msg, data)
            if settings.DEBUG or request.GET.get("debug") == "1":
                return HttpResponse(
                    f"<h3>Erro ao criar PIX</h3><pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre>",
                    content_type="text/html"
                )
            messages.error(request, "Não foi possível iniciar o PIX. Tente novamente.")
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        # Dados do PIX (QR)
        payment_id = data.get("id")
        pio = (data.get("point_of_interaction") or {})
        tdata = (pio.get("transaction_data") or {})
        qr_code_text = tdata.get("qr_code")
        qr_code_base64 = tdata.get("qr_code_base64")
        ticket_url = tdata.get("ticket_url")  # página do MP com o QR

        if not (qr_code_text and qr_code_base64):
            logging.error("PIX sem qr_code/qr_code_base64: %r", data)
            if settings.DEBUG or request.GET.get("debug") == "1":
                return HttpResponse(
                    f"<h3>PIX sem QR</h3><pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre>",
                    content_type="text/html"
                )
            messages.error(request, "Não foi possível obter o QR do PIX. Tente de novo.")
            return redirect("inscricoes:ver_inscricao", inscricao.id)

        # Registra/atualiza pagamento como pendente
        Pagamento.objects.update_or_create(
            inscricao=inscricao,
            defaults={
                "valor": inscricao.evento.valor_inscricao,
                "status": Pagamento.StatusPagamento.PENDENTE,
                "metodo": Pagamento.MetodoPagamento.PIX,
                "transacao_id": str(payment_id or ""),
            }
        )

        # Renderiza a página com o QR no seu site
        return render(request, "pagamentos/pix.html", {
            "inscricao": inscricao,
            "payment_id": payment_id,
            "qr_code_text": qr_code_text,
            "qr_code_base64": qr_code_base64,  # data URI pronto para <img src="{{ qr_code_base64 }}">
            "ticket_url": ticket_url,
            "expires_at": expires_at,
            "valor": float(inscricao.evento.valor_inscricao),
        })

    except Exception as e:
        logging.exception("Erro ao criar pagamento PIX: %s", e)
        if settings.DEBUG or request.GET.get("debug") == "1":
            return HttpResponse(f"<h3>Exceção ao criar PIX</h3><pre>{e}</pre>", content_type="text/html")
        messages.error(request, "Erro ao iniciar PIX. Tente novamente.")
        return redirect("inscricoes:ver_inscricao", inscricao.id)


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
    Página pública: participante digita o CPF e vê todas as inscrições dele.
    Mostra apenas eventos onde foi selecionado, com botões de pagamento.
    """
    participante = None
    inscricoes = []
    cpf_informado = (request.POST.get("cpf") or request.GET.get("cpf") or "").strip()

    def _buscar_por_cpf(cpf_raw: str):
        """Normaliza e busca inscrições selecionadas do participante."""
        cpf_limpo = "".join(c for c in (cpf_raw or "") if c.isdigit())
        if len(cpf_limpo) != 11:
            messages.error(request, "Informe um CPF válido (11 dígitos).")
            return None, []
        try:
            p = Participante.objects.get(cpf=cpf_limpo)
        except Participante.DoesNotExist:
            messages.error(request, "CPF não encontrado em nosso sistema.")
            return None, []
        qs = (Inscricao.objects
              .filter(participante=p, foi_selecionado=True)  # <- somente selecionadas
              .select_related("evento", "paroquia")
              .order_by("-id"))
        if not qs.exists():
            messages.info(request, "Nenhuma inscrição selecionada encontrada para este CPF.")
        return p, list(qs)

    # Se veio CPF por POST ou por querystring (?cpf=...), tenta buscar
    if cpf_informado:
        participante, inscricoes = _buscar_por_cpf(cpf_informado)

    # Envia a política pra exibir a logo no topo
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
            messages.error(request, "CPF inválido. Digite apenas números.")
        else:
            participante = Participante.objects.filter(cpf=cpf).first()
            if participante:
                # lista TODAS as inscrições do participante
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
    Relatório consolidado por paróquia (e breakdown por evento).
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

    # filtros de período (pela data_pagamento, caindo para data_inscricao se nulo)
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

    # agregado por paróquia
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

    # monta índice evento por paróquia
    eventos_idx = {}
    for row in por_evento:
        pid = row["inscricao__paroquia_id"]
        eventos_idx.setdefault(pid, []).append(row)

    # enriquece com taxa e líquido
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

    # lista de paróquias p/ filtro
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
    Exporta CSV do relatório consolidado (mesmos filtros da tela).
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
    w.writerow(["Paróquia", "Qtd Pagamentos", "Total Bruto", f"Taxa ({fee_percent}%)", "Líquido"])

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
        # aqui você pode tratar mensagens e status (entregue/lido/falha)
        return JsonResponse({"ok": True})

    return HttpResponse(status=405)

def editar_politica_reembolso(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)
    politica, _ = PoliticaReembolso.objects.get_or_create(evento=evento)

    if request.method == 'POST':
        form = PoliticaReembolsoForm(request.POST, instance=politica)
        if form.is_valid():
            form.save()
            messages.success(request, 'Política de reembolso salva com sucesso.')
            # volte para o painel da paróquia ou para a lista de eventos — ajuste se preferir
            return redirect('inscricoes:admin_paroquia_painel', paroquia_id=evento.paroquia_id)
    else:
        form = PoliticaReembolsoForm(instance=politica)

    return render(request, 'inscricoes/editar_politica_reembolso.html', {
        'evento': evento,
        'form': form,
    })

@login_required
def admin_paroquia_create_admin(request):
    # Só Admin da Paróquia (da própria) ou Admin Geral
    if not (hasattr(request.user, "tipo_usuario") and (request.user.is_admin_paroquia() or request.user.is_admin_geral())):
        messages.error(request, "Você não tem permissão para acessar esta página.")
        return redirect("inscricoes:home_redirect")

    # Paróquia “alvo”:
    # - Admin da paróquia: sempre a sua
    # - Admin geral: pode usar ?paroquia=<id> (opcional); senão, também usamos a sua
    paroquia = request.user.paroquia
    if request.user.is_admin_geral():
        pid = request.GET.get("paroquia")
        if pid:
            paroquia = get_object_or_404(Paroquia, pk=pid)

    if not paroquia:
        messages.error(request, "Seu usuário não está vinculado a uma paróquia.")
        return redirect("inscricoes:admin_geral_dashboard")

    if request.method == "POST":
        form = AdminParoquiaCreateForm(request.POST)
        if form.is_valid():
            form.save(paroquia=paroquia)
            messages.success(request, "Administrador de paróquia criado com sucesso.")
            # volta para a mesma página (mantendo ?paroquia=) para ver a lista atualizada
            url = reverse("inscricoes:admin_paroquia_create_admin")
            if request.user.is_admin_geral() and request.GET.get("paroquia"):
                url += f"?paroquia={paroquia.id}"
            return redirect(url)
    else:
        form = AdminParoquiaCreateForm()

    # Lista de admins desta paróquia
    admins = (
        User.objects
            .filter(tipo_usuario="admin_paroquia", paroquia=paroquia)
            .order_by("first_name", "last_name", "username")
    )

    ctx = {
        "form": form,
        "paroquia": paroquia,
        "admins": admins,  # << para o template renderizar a tabela + botão Excluir
        "current_year": timezone.now().year,
        "is_admin_geral": request.user.is_admin_geral(),
    }
    return render(request, "inscricoes/admin_paroquia_criar_admin.html", ctx)


@login_required
def admin_paroquia_delete_admin(request, user_id: int):
    if request.method != "POST":
        messages.error(request, "Método inválido.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if not (hasattr(request.user, "tipo_usuario") and (request.user.is_admin_paroquia() or request.user.is_admin_geral())):
        messages.error(request, "Você não tem permissão para esta ação.")
        return redirect("inscricoes:home_redirect")

    alvo = get_object_or_404(User, pk=user_id)

    # precisa existir paróquia no usuário que executa
    if not request.user.paroquia and not request.user.is_admin_geral():
        messages.error(request, "Seu usuário não está vinculado a uma paróquia.")
        return redirect("inscricoes:admin_geral_dashboard")

    # segurança: só excluir admin_paroquia da MESMA paróquia
    # (admin geral pode excluir de qualquer paróquia)
    if alvo.tipo_usuario != "admin_paroquia":
        messages.error(request, "Somente usuários 'admin_paroquia' podem ser excluídos aqui.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if request.user.is_admin_paroquia() and alvo.paroquia_id != request.user.paroquia_id:
        messages.error(request, "Você não pode excluir um administrador de outra paróquia.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    if alvo.id == request.user.id:
        messages.error(request, "Você não pode excluir o próprio usuário.")
        return redirect("inscricoes:admin_paroquia_create_admin")

    nome = alvo.get_full_name() or alvo.username
    alvo.delete()
    messages.success(request, f"Administrador '{nome}' excluído com sucesso.")

    # preservar ?paroquia= para admin geral
    url = reverse("inscricoes:admin_paroquia_create_admin")
    if request.user.is_admin_geral() and request.GET.get("paroquia"):
        url += f"?paroquia={request.GET.get('paroquia')}"
    return redirect(url)

try:
    from .finance_calc import calcular_financeiro_evento as _calc_financeiro_evento_external
except Exception:
    _calc_financeiro_evento_external = None


# ===== CÁLCULO FINANCEIRO (com fallback) =====
TAXA_SISTEMA_DEFAULT = Decimal("3.00")

def calcular_financeiro_evento(evento, taxa_percentual=TAXA_SISTEMA_DEFAULT):
    """
    Se existir .finance_calc, delega para lá. Caso contrário,
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
        messages.error(request, "Não há valor a repassar para este evento.")
        return redirect("inscricoes:repasse_evento_detalhe", evento_id=evento.id)

    try:
        sdk, cfg = mp_owner_client()
    except Exception as e:
        messages.error(request, f"Configuração do Mercado Pago (DONO) ausente/inválida: {e}")
        return redirect("inscricoes:repasse_evento_detalhe", evento_id=evento.id)

    notification_url = (cfg.notificacao_webhook_url or "").strip()

    with transaction.atomic():
        # Reutiliza (lock) ou cria um único repasse pendente por evento
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
            # atualiza valores (se mudou algo desde a criação)
            repasse.valor_base = fin["base_repasse"]
            repasse.taxa_percentual = fin["taxa_percent"]
            repasse.valor_repasse = fin["valor_repasse"]

        body = {
            "transaction_amount": float(repasse.valor_repasse),
            "description": f"Repasse taxa sistema – {evento.nome}",
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
        # Não quebrar o fluxo de callbacks
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

    # Permissão básica: admin geral ou admin da mesma paróquia
    if not (getattr(request.user, "is_superuser", False)
            or (hasattr(request.user, "is_admin_geral") and request.user.is_admin_geral())
            or (hasattr(request.user, "is_admin_paroquia") and request.user.is_admin_paroquia()
                and request.user.paroquia_id == evento.paroquia_id)):
        return HttpResponseForbidden("Você não tem permissão para editar este evento.")

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
            messages.success(request, "Vídeo do evento salvo com sucesso!")
            # redirecione para a própria página ou para o detalhe do evento
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

@never_cache
def painel_sorteio(request, slug):
    """
    Página pública (telão). Envia data/hora do servidor (localtime) para o template.
    """
    evento = get_object_or_404(EventoAcampamento, slug=slug)

    agora = timezone.localtime()  # respeita TIME_ZONE e USE_TZ=True
    context = {
        "evento": evento,
        "server_now_iso": agora.isoformat(),            # para JS iniciar o relógio
        "server_date": agora.strftime("%d/%m/%Y"),      # para render imediato
        "server_time": agora.strftime("%H:%M:%S"),      # para render imediato
    }
    return render(request, "inscricoes/painel_sorteio.html", context)


@never_cache
def api_selecionados(request, slug):
    """
    Retorna todos os selecionados do evento.
    - Para eventos de CASAIS, une o par num único item:
      {"casal": true, "p1": {...}, "p2": {...}}
    - Para os demais, retorna itens individuais: {"id":..., "nome":...}
    A ordenação é crescente por id, então o último é o mais “recente”.
    """
    evento = get_object_or_404(EventoAcampamento, slug=slug)

    qs = (
        Inscricao.objects
        .select_related(
            "participante", "evento",
            "inscricao_pareada__participante",  # fwd one-to-one
            "pareada_por__participante",        # reverse one-to-one
        )
        .filter(evento=evento, foi_selecionado=True)
        .order_by("id")
    )

    def serializa_part(i: Inscricao) -> dict:
        p = i.participante
        # foto: CloudinaryField pode não existir/estar vazio
        foto_url = None
        try:
            f = getattr(p, "foto", None)
            if f:
                foto_url = f.url
        except Exception:
            foto_url = None
        return {
            "id": i.id,
            "nome": p.nome,
            "cidade": getattr(p, "cidade", "") or "",
            "estado": getattr(p, "estado", "") or "",
            "foto": foto_url,
        }

    data = []

    if (evento.tipo or "").lower() == "casais":
        # agrupa casais sem duplicar
        vistos = set()
        pares = []
        avulsos = []

        for i in qs:
            par = i.par  # propriedade do modelo que resolve o pareamento em qualquer ponta
            if par and par.foi_selecionado and par.evento_id == i.evento_id:
                key = tuple(sorted([i.id, par.id]))
                if key in vistos:
                    continue
                vistos.add(key)
                p1 = serializa_part(i)
                p2 = serializa_part(par)
                rank = max(i.id, par.id)  # aproxima “mais recente”
                pares.append((rank, {"casal": True, "p1": p1, "p2": p2}))
            else:
                # sem par selecionado (ou não pareado): cai como individual
                avulsos.append((i.id, serializa_part(i)))

        pares.sort(key=lambda t: t[0])
        avulsos.sort(key=lambda t: t[0])
        data = [d for _, d in pares] + [d for _, d in avulsos]
    else:
        # eventos normais: só individuais
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
    # registra visita (não falha se o modelo não existir)
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

    # Eventos com inscrições abertas
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
    Página pública de entrada.
    Template: inscricoes/site_eismeaqui.html
    """
    form = LeadLandingForm()
    ctx = _landing_context(request, form)
    return render(request, "inscricoes/site_eismeaqui.html", ctx)


@require_POST
def contato_enviar(request: HttpRequest) -> HttpResponse:
    """
    Processa o formulário de contato da landing.
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

    # E-mail de confirmação ao usuário
    try:
        assunto_user = "Recebemos sua mensagem – eismeaqui.app"
        texto_user = (
            f"Olá {nome},\n\nRecebemos sua mensagem e entraremos em contato em breve.\n\n"
            f"Resumo enviado:\nWhatsApp: {whatsapp}\nMensagem: {mensagem}\n\n"
            "Deus abençoe!\nEquipe eismeaqui.app"
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
    Lista publicações da paróquia do usuário (admin paroquia) ou,
    para admin geral, aceita ?paroquia=<id> para filtrar.
    """
    if _user_is_admin_geral(request.user):
        pid = request.GET.get("paroquia") or getattr(request.user, "paroquia_id", None)
        paroquia = get_object_or_404(Paroquia, pk=pid) if pid else getattr(request.user, "paroquia", None)
    elif _user_is_admin_paroquia(request.user):
        paroquia = getattr(request.user, "paroquia", None)
        if not paroquia:
            messages.error(request, "Sua conta não está vinculada a uma paróquia.")
            return redirect("inscricoes:home_redirect")
    else:
        messages.error(request, "Sem permissão.")
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
            messages.error(request, "Sua conta não está vinculada a uma paróquia.")
            return redirect("inscricoes:home_redirect")
    else:
        messages.error(request, "Sem permissão.")
        return redirect("inscricoes:home_redirect")

    if request.method == "POST":
        form = ComunicadoForm(request.POST, request.FILES)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.paroquia = paroquia
            obj.save()
            messages.success(request, "Publicação criada com sucesso!")
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
    # permissão: admin da mesma paróquia ou admin geral
    if not _user_is_admin_geral(request.user):
        if not _user_is_admin_paroquia(request.user) or request.user.paroquia_id != obj.paroquia_id:
            messages.error(request, "Sem permissão para editar esta publicação.")
            return redirect("inscricoes:publicacoes_list")

    if request.method == "POST":
        form = ComunicadoForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Publicação atualizada!")
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
            messages.error(request, "Sem permissão para excluir esta publicação.")
            return redirect("inscricoes:publicacoes_list")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Publicação excluída.")
        return redirect("inscricoes:publicacoes_list")

    return render(request, "inscricoes/publicacao_confirm_delete.html", {"obj": obj})

def comunicado_detalhe(request, pk: int):
    from .models import Comunicado  # evita import circular
    obj = get_object_or_404(Comunicado, pk=pk)
    # se tiver flag publicado e quiser ocultar os não publicados:
    try:
        if hasattr(obj, "publicado") and not obj.publicado:
            # admin pode visualizar, público não
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

    # Status (via datas, pois 'status_inscricao' é property)
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

    # ---- Anotações + status_code para usar na UI se quiser
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

    # ---- Paginação
    paginator  = Paginator(qs, 12)
    page_obj   = paginator.get_page(request.GET.get("page"))
    eventos_pg = page_obj.object_list

    # ---- KPIs (gerais da paróquia)
    # Inscrições totais/confirmadas por paróquia
    insc_paroquia = Inscricao.objects.filter(evento__paroquia=paroquia)
    total_inscricoes = insc_paroquia.count()
    total_inscricoes_confirmadas = insc_paroquia.filter(pagamento_confirmado=True).count()

    # KPIs de eventos (base no queryset já filtrado)
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
    # admin da própria paróquia
    return getattr(user, "paroquia_id", None) == inscricao.paroquia_id

@require_POST
def toggle_selecao_inscricao(request, pk: int):
    inscricao = get_object_or_404(Inscricao, pk=pk)

    if not _pode_gerir_inscricao(request.user, inscricao):
        return HttpResponseForbidden("Sem permissão.")

    # esperado: selected="true" | "false"
    selected_raw = request.POST.get("selected", "").lower().strip()
    selected = selected_raw in ("1", "true", "t", "on", "yes", "y")

    with transaction.atomic():
        antes = inscricao.foi_selecionado
        inscricao.foi_selecionado = selected
        inscricao.save(update_fields=["foi_selecionado"])

    return JsonResponse({
        "ok": True,
        "inscricao_id": inscricao.id,
        "selected": inscricao.foi_selecionado,
        "changed": antes != inscricao.foi_selecionado,
        "msg": "Participante selecionado" if inscricao.foi_selecionado else "Participante desmarcado",
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

    # Permissão: superuser/admin_geral vê tudo; admin_paroquia só da própria paróquia
    u = request.user
    if (not getattr(u, "is_superuser", False)
        and getattr(u, "tipo_usuario", "") != "admin_geral"
        and getattr(u, "paroquia_id", None) != inscricao.paroquia_id):
        return HttpResponseForbidden("Você não tem permissão para ver esta inscrição.")

    # Ministérios só para evento do tipo "servos"
    ministerios = []
    if (inscricao.evento.tipo or "").lower() == "servos":
        ministerios = list(
            Ministerio.objects.filter(ativo=True)
            .order_by("nome")
        )

    # Grupos: AGORA SEMPRE (catálogo global)
    # Se quiser limitar aos grupos “usados” neste evento, troque por:
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
            "ministerios": ministerios,  # só será lista se tipo=servos
            "grupos": grupos,            # agora sempre presente
        },
    )


from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from .models import EventoAcampamento

def evento_configuracoes(request, evento_id):
    # evento_id é UUID (vide urls)
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
    "endereco": ["endereco", "endereço", "address", "rua", "logradouro"],
    "numero": ["numero", "número", "nro", "num"],
    "bairro": ["bairro", "district"],
    "cidade": ["cidade", "city", "municipio", "município"],
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
        "endereco": ["endereco", "endereço", "logradouro", "rua"],
        "numero": ["numero", "número", "num", "nro"],
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
        if not (nome or idade_raw or tel):   # ✅ nada de "ou" em Python
            continue
        try:
            idade = int(idade_raw) if idade_raw else 0
        except Exception:
            idade = 0
        filhos.append({"nome": nome, "idade": idade, "telefone": tel})
    return filhos

def _save_binary_to_filefield(instance, candidate_field_names, filename, data) -> str | None:
    field_names = {f.name for f in instance._meta.get_fields() if hasattr(f, "attname")}
    for name in candidate_field_names:
        if name not in field_names:
            continue
        sid = transaction.savepoint()
        try:
            current = getattr(instance, name, None)
            if hasattr(current, "save"):
                current.save(filename, ContentFile(data), save=True)
                transaction.savepoint_commit(sid)
                return name
            cf = ContentFile(data, name=filename)
            setattr(instance, name, cf)
            instance.save(update_fields=[name])
            transaction.savepoint_commit(sid)
            return name
        except Exception:
            transaction.savepoint_rollback(sid)
            continue
    return None

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
                            participante=participante1,   # ✅ sem espaço
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

                        # FOTO: lê bytes agora (uma vez) e salva só após o commit
                        foto_file = request.FILES.get("foto_casal")
                        data = None
                        base_name = "foto_casal.jpg"

                        if foto_file:
                            data = foto_file.read()
                            base_name = getattr(foto_file, "name", base_name)
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
                                Filho.objects.create(inscricao=insc1, nome=f.get("nome",""), idade=f.get("idade") or 0, telefone=f.get("telefone",""))
                                Filho.objects.create(inscricao=insc2, nome=f.get("nome",""), idade=f.get("idade") or 0, telefone=f.get("telefone",""))

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
            # (e evita “transação quebrada” continuando a fazer queries)
            raise

    return render(request, "inscricoes/formulario_casais.html", {
        "evento": evento,
        "politica": politica,
        "form": form_participante,
        "form_insc": form_inscricao,
        "etapa": etapa,
    })



# --- helper: resolve o tipo de formulário efetivo do evento ---
def _tipo_formulario_evento(evento) -> str:
    """
    Retorna o 'tipo efetivo' de formulário que deve ser usado para o evento.
    Regra: se evento.tipo == 'servos' e estiver vinculado a um evento relacionado
    cujo tipo seja 'casais', o formulário a usar é o de 'casais'.
    Caso contrário, retorna evento.tipo em minúsculas.
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
        return HttpResponseForbidden("Sem permissão.")

    ministerio_id = (request.POST.get("ministerio_id") or "").strip()
    is_coord = (request.POST.get("is_coordenador") or "").lower() in {"1","true","on","yes","sim"}

    # Helper pra voltar para a MESMA página
    def back():
        return redirect(request.META.get("HTTP_REFERER") or
                        reverse("inscricoes:ver_inscricao", args=[inscricao.id]))

    # Se veio vazio: remover alocação
    if not ministerio_id:
        qs = AlocacaoMinisterio.objects.filter(inscricao=inscricao, evento=inscricao.evento)
        if qs.exists():
            qs.delete()
            messages.success(request, "Removido(a) do ministério.")
        else:
            messages.info(request, "Este(a) participante não estava em nenhum ministério.")
        return back()

    ministerio = get_object_or_404(Ministerio, pk=ministerio_id)

    aloc, created = AlocacaoMinisterio.objects.get_or_create(
        inscricao=inscricao,
        evento=inscricao.evento,
        defaults={"ministerio": ministerio, "is_coordenador": is_coord},
    )

    if created:
        # Tentar validar (pode falhar na regra de “um coordenador por ministério/evento”)
        try:
            aloc.full_clean()
            aloc.save()
            messages.success(request, f"{inscricao.participante.nome} alocado(a) em {ministerio.nome}.")
        except ValidationError as e:
            # Apaga a criação que não passou na validação
            aloc.delete()
            # Pega mensagem amigável, se existir em is_coordenador
            msg = "; ".join(e.message_dict.get("is_coordenador", e.messages))
            messages.error(request, msg or "Não foi possível salvar a alocação.")
        return back()

    # Já havia alocação → atualizar ministério e/ou coordenação
    antigo = aloc.ministerio.nome
    aloc.ministerio = ministerio
    aloc.is_coordenador = is_coord
    try:
        aloc.full_clean()   # <- onde a sua validação do “1 coordenador” roda
        aloc.save(update_fields=["ministerio", "is_coordenador"])
        if antigo != ministerio.nome:
            messages.success(request, f"Movido(a) de {antigo} para {ministerio.nome}.")
        else:
            messages.success(request, f"Configuração de coordenação atualizada para {ministerio.nome}.")
    except ValidationError as e:
        msg = "; ".join(e.message_dict.get("is_coordenador", e.messages))
        messages.error(request, msg or "Não foi possível atualizar a alocação.")
    return back()


@login_required
@require_POST
def alocar_grupo(request, inscricao_id: int):
    insc = get_object_or_404(
        Inscricao.objects.select_related("evento", "paroquia", "participante"),
        pk=inscricao_id
    )
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != insc.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("inscricoes:ver_inscricao", args=[insc.id])

    grupo_raw = (request.POST.get("grupo_id") or "").strip()

    if not grupo_raw:
        deleted, _ = AlocacaoGrupo.objects.filter(inscricao=insc, evento=insc.evento).delete()
        messages.success(request, "Alocação de grupo removida." if deleted else "A inscrição não estava alocada a nenhum grupo.")
        return redirect(next_url)

    try:
        grupo_id = int(grupo_raw)
    except ValueError:
        messages.error(request, "Grupo inválido.")
        return redirect(next_url)

    grupo = get_object_or_404(Grupo, pk=grupo_id)

    obj, created = AlocacaoGrupo.objects.update_or_create(
        inscricao=insc, evento=insc.evento, defaults={"grupo": grupo}
    )

    if created:
        messages.success(request, f"{insc.participante.nome} alocado(a) no grupo “{grupo.nome}”.")
    else:
        messages.success(request, f"Grupo de {insc.participante.nome} atualizado para “{grupo.nome}”.")

    return redirect(next_url)

@login_required
def alocar_em_massa(request: HttpRequest, evento_id: int) -> HttpResponse:
    """
    Tela e ação para alocar várias inscrições de uma vez em:
      - Grupo (qualquer evento)
      - Ministério (apenas se evento.tipo == 'servos')
    Mantém o usuário nesta mesma página (PRG: POST -> redirect para a mesma URL).
    """
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    # Permissão: admin_geral vê tudo; admin_paroquia apenas a própria paróquia
    u = request.user
    is_admin_paroquia = _user_is_admin_paroquia(u)
    is_admin_geral = _user_is_admin_geral(u)

    if not (is_admin_paroquia or is_admin_geral):
        return HttpResponseForbidden("Sem permissão.")
    if is_admin_paroquia and getattr(u, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão para este evento.")

    # Inscrições deste evento (fonte da grade)
    inscricoes_qs = (
        Inscricao.objects
        .filter(evento=evento)
        .select_related("participante")
        .order_by("participante__nome")
    )

    # Catálogos GLOBAIS (NÃO filtrar por evento)
    # Opcional: já trazendo contagem de alocados no evento para exibir na UI
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
        inscricao_ids = request.POST.getlist("inscricao_ids")  # múltiplos
        ministerio_id = request.POST.get("ministerio_id") or None
        grupo_id = request.POST.get("grupo_id") or None
        is_coord = (request.POST.get("is_coordenador") == "on")
        funcao_default = (request.POST.get("funcao_default") or "").strip()

        if not inscricao_ids:
            messages.warning(request, "Selecione pelo menos um participante.")
            return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))

        # Apenas inscrições do próprio evento
        alvo_qs = inscricoes_qs.filter(pk__in=inscricao_ids)

        # Valida catálogos
        m_obj = None
        g_obj = None

        # Ministério só faz sentido para evento do tipo "Servos"
        if ministerio_id:
            if (evento.tipo or "").lower() != "servos":
                messages.error(request, "Este evento não é do tipo Servos — não é possível alocar ministérios aqui.")
                return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))
            m_obj = get_object_or_404(Ministerio, pk=ministerio_id)

        if grupo_id:
            g_obj = get_object_or_404(Grupo, pk=grupo_id)

        sucesso_m, sucesso_g, erros = 0, 0, 0

        with transaction.atomic():
            for ins in alvo_qs:
                # ====== Ministério ======
                if m_obj:
                    try:
                        # Um registro por inscrição (OneToOne). Se existir, atualiza; senão cria.
                        aloc_min, _created = AlocacaoMinisterio.objects.get_or_create(
                            inscricao=ins,
                            defaults={
                                "evento": evento,
                                "ministerio": m_obj,
                                "funcao": (funcao_default or None),
                                "is_coordenador": False,  # decide abaixo
                            },
                        )
                        # Garanta que evento e ministerio são deste contexto
                        aloc_min.evento = evento
                        aloc_min.ministerio = m_obj

                        # Coordenador: permite só 1 por (evento, ministério)
                        if is_coord:
                            existe_coord = (
                                AlocacaoMinisterio.objects
                                .filter(evento=evento, ministerio=m_obj, is_coordenador=True)
                                .exclude(pk=aloc_min.pk)
                                .exists()
                            )
                            if existe_coord:
                                # Mensagem amigável por pessoa; não interrompe o loop
                                messages.error(
                                    request,
                                    f"{ins.participante.nome}: já existe um(a) coordenador(a) em “{m_obj.nome}” neste evento. "
                                    "Remova o(a) atual antes de marcar outro(a)."
                                )
                            else:
                                aloc_min.is_coordenador = True
                        else:
                            # Se o checkbox não veio marcado, não mexemos no flag atual (mantém o que já está)
                            pass

                        if funcao_default:
                            aloc_min.funcao = funcao_default

                        aloc_min.full_clean()
                        aloc_min.save()
                        sucesso_m += 1

                    except Exception as e:
                        erros += 1
                        # Evita traceback: registra mensagem e segue
                        messages.error(request, f"{ins.participante.nome}: não foi possível alocar no ministério ({e}).")

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
                        messages.error(request, f"{ins.participante.nome}: não foi possível alocar no grupo ({e}).")

        # Feedback acumulado
        if sucesso_m:
            messages.success(request, f"{sucesso_m} participante(s) alocado(s) ao ministério {m_obj.nome}.")
            if is_coord:
                messages.info(request, "Tentativa de marcar como coordenador(a) aplicada onde possível.")
            if funcao_default:
                messages.info(request, f"Função aplicada: “{funcao_default}”.")
        if sucesso_g:
            messages.success(request, f"{sucesso_g} participante(s) alocado(s) ao grupo {g_obj.nome}.")
        if erros:
            messages.error(request, f"{erros} registro(s) tiveram erro. Revise as mensagens acima.")

        # PRG: volta para a mesma página
        return redirect(reverse("inscricoes:alocar_em_massa", args=[evento.id]))

    # GET: renderiza página
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
        return HttpResponseForbidden("Você não tem permissão para gerenciar este evento.")

    if (evento.tipo or "").lower() != "servos":
        messages.warning(request, "Ministérios só se aplicam a eventos do tipo Servos.")
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
            messages.error(request, "Informe o nome do ministério.")
        else:
            m = Ministerio(evento=evento, nome=nome, descricao=descricao)
            try:
                m.full_clean()
                m.save()
                messages.success(request, f"Ministério “{m.nome}” criado com sucesso.")
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
    """Exclui um ministério (se não tiver alocações)."""
    ministerio = get_object_or_404(
        Ministerio.objects.select_related("evento__paroquia"),
        pk=pk
    )
    evento = ministerio.evento

    if not _can_manage_event(request.user, evento):
        return HttpResponseForbidden("Você não tem permissão para esta ação.")

    if request.method != "POST":
        return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))

    # ⚠️ Trocar inscricoes → alocacoes
    if ministerio.alocacoes.exists():
        messages.error(request, "Não é possível excluir: há servos alocados neste ministério.")
        return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))

    nome = ministerio.nome
    ministerio.delete()
    messages.success(request, f"Ministério “{nome}” excluído com sucesso.")
    return redirect(reverse("inscricoes:ministerios_evento", args=[evento.pk]))


@login_required
def ministerios_home(request, paroquia_id: int):
    """
    Home dos ministérios por paróquia:
    - Lista todos os eventos da paróquia (destaque para 'Servos').
    - Botão para abrir ministérios SEMPRE visível.
    """
    user = request.user
    is_admin_paroquia = _is_admin_paroquia(user)
    is_admin_geral = _is_admin_geral(user)

    if is_admin_paroquia and getattr(user, "paroquia_id", None) != paroquia_id and not is_admin_geral:
        messages.error(request, "Você não pode acessar os ministérios de outra paróquia.")
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
        return HttpResponseForbidden("Sem permissão para este evento.")

    if (evento.tipo or "").lower() != "servos":
        messages.error(request, "Ministérios só são permitidos para eventos do tipo Servos.")
        return redirect("inscricoes:ministerios_evento", evento.id)

    if request.method == "POST":
        form = MinisterioForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.evento = evento
            obj.full_clean()
            obj.save()
            messages.success(request, "Ministério cadastrado com sucesso.")
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
    Página de Ações & Configurações da paróquia:
    - Admin da paróquia: usa a paróquia vinculada ao usuário.
    - Admin geral: precisa informar paroquia_id (ex.: /admin-paroquia/acoes/3/).
    """
    user = request.user

    # Detecta papéis (mesma lógica do seu painel)
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

    # Seleção da paróquia conforme papel
    if is_admin_paroquia:
        paroquia = getattr(user, "paroquia", None)
        if not paroquia:
            messages.error(request, "⚠️ Sua conta não está vinculada a uma paróquia.")
            return redirect("inscricoes:logout")

        # se tentarem acessar outra paróquia via URL, redireciona para a correta
        if paroquia_id and int(paroquia_id) != getattr(user, "paroquia_id", None):
            return redirect(reverse("inscricoes:admin_paroquia_acoes"))
    elif is_admin_geral:
        if not paroquia_id:
            messages.error(request, "⚠️ Paróquia não especificada.")
            return redirect("inscricoes:admin_geral_list_paroquias")
        paroquia = get_object_or_404(Paroquia, id=paroquia_id)
    else:
        messages.error(request, "⚠️ Você não tem permissão para acessar esta página.")
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
    # mesma regra que você já usa em outras views
    if getattr(user, "is_superuser", False) or getattr(user, "tipo_usuario", "") == "admin_geral":
        return True
    return getattr(user, "tipo_usuario", "") == "admin_paroquia" and getattr(user, "paroquia_id", None) == getattr(evento, "paroquia_id", None)

# ==============================================================
# Aliases amigáveis de status (front pode mandar "pago", etc.)
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
        return HttpResponseBadRequest("Inscrição não encontrada")

    # ===== Permissão =====
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

    # valida código final
    codigos_validos = {c for c, _ in InscricaoStatus.choices}
    if new_status not in codigos_validos:
        return JsonResponse(
            {
                "ok": False,
                "error": "Status inválido.",
                "recebido": new_status,
                "validos": sorted(codigos_validos),
            },
            status=400,
        )

    # aplica transição
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
    total_participantes = inscricoes.count()

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

    def _get_birth(insc: Inscricao):
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

    for insc in inscricoes:
        insc.idade = _calc_age(_get_birth(insc), ref_date)

    # -------- Pegar "par" dentro de um mesmo evento (se existir esse vínculo no modelo) --------
    def _par_de(insc: Inscricao):
        try:
            p = insc.par
            if p:
                return p
        except Exception:
            pass
        if getattr(insc, "inscricao_pareada_id", None):
            return getattr(insc, "inscricao_pareada", None)
        return getattr(insc, "pareada_por", None)

    # -------- Flags de tipo --------
    tipo_evento = (getattr(evento, "tipo", "") or "").lower()
    rel = getattr(evento, "evento_relacionado", None)
    tipo_rel = (getattr(rel, "tipo", "") or "").lower() if rel else ""
    is_evento_casais = (tipo_evento == "casais")
    is_servos_de_casal = (tipo_evento == "servos" and rel and tipo_rel == "casais")

    # ======================================================================
    # Servos vinculados a casal — lógica ROBUSTA de pareamento e dedup
    # ======================================================================
    linhas = []

    if is_evento_casais:
        for insc in inscricoes:
            par = _par_de(insc)
            if par and getattr(par, "id", None) and insc.id and not (insc.id < par.id):
                continue
            setattr(insc, "par_inscrito", par if par else None)
            linhas.append(insc)

    elif is_servos_de_casal:
        # 1) Mapa de pares vindo do evento de CASAIS relacionado (se existir)
        par_map = {}  # participante_id -> parceiro_participante_id
        if rel:
            casal_qs = (
                Inscricao.objects.filter(evento=rel)
                .select_related("participante")
                .only("id", "participante_id", "inscricao_pareada_id")
            )
            # Constrói o mapa usando o mesmo helper _par_de
            for insc_casal in casal_qs:
                par = _par_de(insc_casal)
                if par:
                    a = getattr(insc_casal, "participante_id", None)
                    b = getattr(par, "participante_id", None)
                    if a and b:
                        par_map[a] = b
                        par_map[b] = a

        # 2) Fallback por atributos do PARTICIPANTE (conjuge_id / spouse_id / etc.)
        def _partner_pid_from_participant(participante):
            # tente várias convenções comuns sem quebrar caso não exista
            for attr in ("conjuge_id", "parceiro_id", "spouse_id", "par_id", "conjugue_id", "conjuge__id"):
                pid = getattr(participante, attr, None)
                if pid:
                    return pid
            # às vezes vem o objeto relacionado:
            for obj_attr in ("conjuge", "parceiro", "spouse", "par"):
                obj = getattr(participante, obj_attr, None)
                pid = getattr(obj, "id", None)
                if pid:
                    return pid
            return None

        # 3) Também tente parear dentro do PRÓPRIO evento de servos (se alguém armazenou esse vínculo)
        servos_by_part = {i.participante_id: i for i in inscricoes}

        def _find_partner_inscricao(insc: Inscricao):
            pid = getattr(insc, "participante_id", None)
            if not pid:
                return None

            # a) via evento de casais relacionado
            pid_par = par_map.get(pid)
            if pid_par:
                insc_par = servos_by_part.get(pid_par)
                if insc_par:
                    return insc_par

            # b) via atributos do participante
            participante = getattr(insc, "participante", None)
            if participante:
                pid_par_b = _partner_pid_from_participant(participante)
                if pid_par_b:
                    insc_par_b = servos_by_part.get(pid_par_b)
                    if insc_par_b:
                        return insc_par_b

            # c) via vínculo direto na própria inscrição (caso exista)
            par_local = _par_de(insc)
            if par_local:
                return par_local

            return None

        # Dedup por menor participante_id (quando houver par encontrado)
        vistos = set()
        for insc in inscricoes:
            if insc.id in vistos:
                continue
            par_insc = _find_partner_inscricao(insc)

            if par_insc:
                vistos.add(getattr(par_insc, "id", None))
                # decide quem fica (menor participante_id se possível; senão menor id)
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

    # -------- Contadores --------
    qs = Inscricao.objects.filter(evento=evento)

    total_confirmados = qs.filter(status=InscricaoStatus.PAG_CONFIRMADO).count()

    total_selecionados = qs.filter(
        status__in=[
            InscricaoStatus.CONVOCADA,
            InscricaoStatus.PAG_PENDENTE,
            InscricaoStatus.PAG_CONFIRMADO,
        ]
    ).count()

    total_pendentes = qs.filter(
        status__in=[
            InscricaoStatus.ENVIADA,
            InscricaoStatus.EM_ANALISE,
            InscricaoStatus.APROVADA,
            InscricaoStatus.LISTA_ESPERA,
            InscricaoStatus.CONVOCADA,
            InscricaoStatus.PAG_PENDENTE,
        ]
    ).count()

    context = {
        "evento": evento,
        "participantes": linhas,               # já deduplicado
        "is_evento_casais": (tipo_evento == "casais"),
        "is_servos_de_casal": is_servos_de_casal,
        "valor_inscricao": getattr(evento, "valor_inscricao", None),
        "total_participantes": total_participantes,
        "total_confirmados": total_confirmados,
        "total_selecionados": total_selecionados,
        "total_pendentes": total_pendentes,
        "status_choices": InscricaoStatus.choices,
    }
    return render(request, "inscricoes/evento_participantes.html", context)

from .forms import MinisterioForm

@require_http_methods(["GET", "POST"])
@login_required
def ministerio_novo(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if (evento.tipo or "").lower() != "servos":
        messages.error(request, "Ministérios só fazem sentido em eventos do tipo Servos.")
        return redirect("inscricoes:ministerios_evento", evento_id=evento.id)

    # Permissão
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

    if request.method == "POST":
        form = MinisterioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Ministério criado no catálogo global.")
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
        return HttpResponseForbidden("Edição do catálogo global restrita ao administrador geral.")

    if request.method == "POST":
        form = MinisterioForm(request.POST, instance=ministerio)
        if form.is_valid():
            form.save()
            messages.success(request, "Ministério atualizado com sucesso.")
            # Volta para a listagem geral de ministérios do sistema
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
    Lista alocados de um ministério *neste evento* e mostra o form para incluir mais.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

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
    Handler do POST de alocação via botão/linha separada.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

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
        return HttpResponseForbidden("Sem permissão.")

    nome = aloc.inscricao.participante.nome
    mid = aloc.ministerio_id
    eid = aloc.evento_id
    aloc.delete()
    messages.success(request, f"{nome} removido(a) do ministério.")
    return redirect(reverse("inscricoes:alocacoes_ministerio", args=[mid, eid]))

@login_required
@require_POST
def toggle_coordenador_ministerio(request, alocacao_id: int):
    aloc = get_object_or_404(
        AlocacaoMinisterio.objects.select_related("evento", "inscricao__participante"),
        pk=alocacao_id
    )
    if not request.user.is_superuser and getattr(request.user, "paroquia_id", None) != aloc.evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

    ativo = (request.POST.get("ativo") or "").strip().lower() in {"1","true","on","yes","sim"}
    aloc.is_coordenador = ativo
    try:
        aloc.full_clean()
        aloc.save(update_fields=["is_coordenador"])
        msg = "marcado(a) como coordenador(a)." if ativo else "removido(a) da coordenação."
        messages.success(request, f"{aloc.inscricao.participante.nome} {msg}")
    except Exception as e:
        messages.error(request, str(e))

    return redirect(reverse("inscricoes:alocacoes_ministerio", args=[aloc.ministerio_id, aloc.evento_id]))

@login_required
def ministerios_evento(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, pk=evento_id)

    # Permissão básica
    if (not request.user.is_superuser
        and getattr(request.user, "paroquia_id", None) != evento.paroquia_id):
        return HttpResponseForbidden("Sem permissão.")

    # IMPORTANTÍSSIMO: o related_name abaixo precisa existir no model de AlocacaoMinisterio
    # class AlocacaoMinisterio(models.Model):
    #     ministerio = models.ForeignKey(Ministerio, related_name="alocacoes", ...)
    #     evento = models.ForeignKey(EventoAcampamento, ...)
    #
    # Se o seu related_name não for "alocacoes", ajuste as 2 linhas com "alocacoes" aqui.

    # Pré-busca: todas as alocações deste evento (para montar a lista e também contagens fallback)
    alocs_qs = (
        AlocacaoMinisterio.objects
        .filter(evento=evento)
        .select_related("inscricao__participante")  # útil para telas de detalhes
        .order_by()  # evita ORDER BY desnecessário que pode afetar o COUNT DISTINCT
    )

    # Query principal dos ministérios
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
    # Se você quer o total geral de pessoas alocadas no evento (soma de todos os ministérios):
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
    Deleta um Ministério (catálogo global) **apenas** se não houver alocações.
    Se vier evento_id (via POST/GET), usamos para voltar à tela do evento.
    """
    ministerio = get_object_or_404(Ministerio, pk=pk)

    # Permissão: superuser ou admin da mesma paróquia de um evento alvo (quando informado)
    evento_id = request.POST.get("evento_id") or request.GET.get("evento_id")
    evento = None
    if evento_id:
        try:
            evento = EventoAcampamento.objects.get(pk=evento_id)
        except EventoAcampamento.DoesNotExist:
            evento = None

    # Regra simples: se não for superuser e houver evento no contexto, só permite se for a mesma paróquia
    if not request.user.is_superuser and evento and getattr(request.user, "paroquia_id", None) != evento.paroquia_id:
        return HttpResponseForbidden("Sem permissão.")

    # Bloqueia exclusão se houver qualquer alocação (em qualquer evento)
    if ministerio.alocacoes.exists():
        messages.error(request, "Não é possível excluir: existem participantes alocados neste ministério.")
        if evento:
            return redirect("inscricoes:ministerios_evento", evento_id=evento.id)
        return redirect("inscricoes:ministerios_home_sem_paroquia")

    nome = ministerio.nome
    ministerio.delete()
    messages.success(request, f"Ministério “{nome}” excluído com sucesso.")
    if evento:
        return redirect("inscricoes:ministerios_evento", evento_id=evento.id)
    return redirect("inscricoes:ministerios_home_sem_paroquia")

@login_required
def alocacoes_ministerio_short(request, pk: int):
    """
    Compat: usuário caiu na rota sem evento_id.
    Tentamos descobrir o último evento onde esse ministério tem alocação
    e redirecionamos para a rota correta. Se não houver, mandamos para a home.
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

    messages.warning(request, "Escolha o evento para esse ministério.")
    return redirect("inscricoes:ministerios_home_sem_paroquia")

from django.db import transaction

def _par_de(insc: Inscricao):
    """Tenta achar a inscrição pareada (par) para eventos de casais."""
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
    Retorna a inscrição do PAR dentro do MESMO evento, cobrindo:
      - Evento de CASAIS: usa o pareamento direto (par, inscricao_pareada, etc).
      - Evento de SERVOS vinculado a um evento de casais: resolve o par via evento_relacionado.
    """
    ev = insc.evento
    tipo_ev = (getattr(ev, "tipo", "") or "").lower()

    # Caso 1: evento de CASAIS — pareamento direto
    if tipo_ev == "casais":
        par = _par_de(insc)
        if par and par.evento_id == insc.evento_id:
            return par
        return None

    # Caso 2: servos "de casal": achar par via evento_relacionado (que é de casais)
    rel = getattr(ev, "evento_relacionado", None)
    tipo_rel = (getattr(rel, "tipo", "") or "").lower() if rel else ""
    if tipo_ev == "servos" and rel and tipo_rel == "casais":
        # inscrição deste participante no evento de casais
        insc_casal = Inscricao.objects.filter(evento=rel, participante_id=insc.participante_id).first()
        if not insc_casal:
            return None
        # o par no evento de casais…
        par_casal = _par_de(insc_casal)
        if not par_casal:
            return None
        # …e a inscrição do par no evento ATUAL (servos)
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

    # --- Permissão (mesma regra da listagem) ---
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
            # 1) ache a inscrição do participante no evento de casais
            insc_casal = (
                Inscricao.objects.filter(evento=rel, participante_id=insc.participante_id)
                .select_related("participante")
                .first()
            )
            if insc_casal:
                # 2) pegue o "par" nessa inscrição de casais
                par_casal = _par_de(insc_casal)
                if par_casal and getattr(par_casal, "participante_id", None):
                    # 3) agora ache a inscrição do PAR no próprio evento de servos
                    partner = (
                        Inscricao.objects.filter(evento=evento, participante_id=par_casal.participante_id)
                        .first()
                    )
        # fallback: se alguém armazenou pareamento direto também em servos
        if partner is None:
            partner = _par_de(insc)

    # --- Persistência (atual + parceiro) ---
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
        "msg": "Seleção atualizada" + (" (par também atualizado)" if partner_id else ""),
    })

from django.utils import timezone

@login_required
@require_POST
def alterar_status_inscricao(request, inscricao_id: int):
    insc = get_object_or_404(Inscricao, id=inscricao_id)
    if not _can_manage_inscricao(request.user, insc):
        return HttpResponseForbidden("Acesso negado.")

    novo = (request.POST.get("status") or "").strip()
    validos = dict(InscricaoStatus.choices)
    if novo not in validos:
        return JsonResponse({"ok": False, "error": "status inválido"}, status=400)

    # Estados que contam como "selecionado" (mantém igual ao seu front)
    estados_selecionado = {
        InscricaoStatus.CONVOCADA,
        InscricaoStatus.PAG_PENDENTE,
        InscricaoStatus.PAG_CONFIRMADO,
    }
    novo_sel = novo in estados_selecionado

    # Pagamento: confirma somente quando status == PAG_CONFIRMADO
    vai_confirmar_pagto = (novo == InscricaoStatus.PAG_CONFIRMADO)

    par = _find_pair_in_same_event(insc)

    with transaction.atomic():
        updates = []

        # status
        if insc.status != novo:
            insc.status = novo
            updates.append("status")

        # seleção (segue a regra acima)
        if insc.foi_selecionado != novo_sel:
            insc.foi_selecionado = novo_sel
            updates.append("foi_selecionado")

        # pagamento_confirmado: true só quando PAG_CONFIRMADO; senão false
        if getattr(insc, "pagamento_confirmado", False) != vai_confirmar_pagto:
            insc.pagamento_confirmado = vai_confirmar_pagto
            updates.append("pagamento_confirmado")

        if updates:
            insc.save(update_fields=updates)

        # Sincroniza o objeto Pagamento (se existir, atualiza; senão cria quando confirmar)
        # - Confirmado  -> status CONFIRMADO + data_pagamento = agora
        # - Pag pendente/convocada/etc -> status PENDENTE (se houver registro)
        # - Outros estados de cancelamento (se você tiver) -> CANCELADO
        from .models import Pagamento  # garante import

        if vai_confirmar_pagto:
            pgto, _ = Pagamento.objects.get_or_create(
                inscricao=insc,
                defaults={
                    "valor": insc.evento.valor_inscricao or 0,
                    "metodo": getattr(Pagamento.MetodoPagamento, "PIX", "pix"),
                }
            )
            pgto.status = Pagamento.StatusPagamento.CONFIRMADO
            pgto.data_pagamento = timezone.now()
            pgto.save(update_fields=["status", "data_pagamento"])
        else:
            # Se não é confirmado, marcamos pendente quando fizer sentido
            pgto = Pagamento.objects.filter(inscricao=insc).first()
            if pgto:
                if novo == InscricaoStatus.PAG_PENDENTE or novo in estados_selecionado:
                    pgto.status = Pagamento.StatusPagamento.PENDENTE
                    pgto.data_pagamento = None
                    pgto.save(update_fields=["status", "data_pagamento"])
                else:
                    # Caso queira tratar como cancelado em estados fora do funil:
                    # pgto.status = Pagamento.StatusPagamento.CANCELADO
                    # pgto.data_pagamento = None
                    # pgto.save(update_fields=["status", "data_pagamento"])
                    pass

        # Se houver PAR, só sincronizamos a "seleção" (não pagamento! pagamento é individual)
        if par and par.foi_selecionado != novo_sel:
            par.foi_selecionado = novo_sel
            par.save(update_fields=["foi_selecionado"])

    return JsonResponse({
        "ok": True,
        "status": insc.status,
        "label": insc.get_status_display(),
        "pagamento_confirmado": bool(insc.pagamento_confirmado),  # <- o front usa isso pro badge
        "foi_selecionado": bool(insc.foi_selecionado),
        "paired_updated": bool(par),
    })

