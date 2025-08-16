# ——— Python stdlib
import os
import json
import logging
from io import BytesIO
from urllib.parse import urljoin
from datetime import timedelta, timezone as dt_tz
from django.utils import timezone


# ——— Terceiros
import mercadopago
import qrcode
from django.views.decorators.http import require_http_methods

# ——— Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

# ——— App (models e forms)
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
    PreferenciasComunicacao
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
    PagamentoForm
)

User = get_user_model()


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


# -------- Usuários Admin Paróquia --------

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

@login_required
def admin_paroquia_painel(request, paroquia_id=None):
    user = request.user

    # --- Detecta papeis com fallback ---
    # is_admin_paroquia: usa método se existir; senão checa tipo_usuario
    if hasattr(user, "is_admin_paroquia") and callable(user.is_admin_paroquia):
        is_admin_paroquia = user.is_admin_paroquia()
    else:
        is_admin_paroquia = getattr(user, "tipo_usuario", "") == "admin_paroquia"

    # is_admin_geral: usa método se existir; senão checa superuser/tipo_usuario
    if hasattr(user, "is_admin_geral") and callable(user.is_admin_geral):
        is_admin_geral = user.is_admin_geral()
    else:
        is_admin_geral = bool(getattr(user, "is_superuser", False)) or (
            getattr(user, "tipo_usuario", "") == "admin_geral"
        )

    # --- Seleção da paróquia conforme o papel ---
    if is_admin_paroquia:
        paroquia = getattr(user, "paroquia", None)
        if not paroquia:
            messages.error(request, "⚠️ Sua conta não está vinculada a uma paróquia.")
            return redirect('inscricoes:logout')
    elif is_admin_geral:
        if not paroquia_id:
            messages.error(request, "⚠️ Paróquia não especificada.")
            return redirect('inscricoes:admin_geral_list_paroquias')
        paroquia = get_object_or_404(Paroquia, id=paroquia_id)
    else:
        messages.error(request, "⚠️ Você não tem permissão para acessar este painel.")
        return redirect('inscricoes:logout')

    # --- Eventos da paróquia (mais recentes primeiro) ---
    if hasattr(EventoAcampamento, "created_at"):
        eventos = (EventoAcampamento.objects
                   .filter(paroquia=paroquia)
                   .order_by('-data_inicio', '-created_at'))
    else:
        eventos = (EventoAcampamento.objects
                   .filter(paroquia=paroquia)
                   .order_by('-data_inicio'))

    return render(request, 'inscricoes/admin_paroquia_painel.html', {
        'paroquia': paroquia,
        'eventos': eventos,
        'is_admin_paroquia': is_admin_paroquia,  # <- use no template
        'is_admin_geral': is_admin_geral,        # <- se precisar
    })

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
def evento_editar(request, pk):
    # código para editar evento
    pass

@login_required
def evento_deletar(request, pk):
    # código para deletar evento
    pass

@login_required
def evento_participantes(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)

    # Verifica se o usuário tem permissão para acessar
    if request.user.is_admin_paroquia():
        if request.user.paroquia != evento.paroquia:
            return HttpResponseForbidden("Acesso negado.")
    elif not request.user.is_admin_geral():
        return HttpResponseForbidden("Acesso negado.")

    participantes = Inscricao.objects.filter(evento=evento).select_related('participante')
    total_participantes = participantes.count()  # Contagem dos participantes

    if request.method == "POST":
        inscricao_id = request.POST.get('inscricao_id')
        foi_selecionado = 'foi_selecionado' in request.POST

        try:
            inscricao = participantes.get(id=inscricao_id)  # garante que seja do evento
        except Inscricao.DoesNotExist:
            return HttpResponse("Inscrição não encontrada", status=404)

        inscricao.foi_selecionado = foi_selecionado
        inscricao.save()
        return redirect('inscricoes:evento_participantes', evento_id=evento.id)

    context = {
        'evento': evento,
        'participantes': participantes,
        'valor_inscricao': evento.valor_inscricao,
        'total_participantes': total_participantes,  # Adiciona ao contexto
    }
    return render(request, 'inscricoes/evento_participantes.html', context)


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

    # Determina qual modelo de inscrição base usar
    if evento.tipo == 'senior':
        inscricao_base = get_object_or_404(InscricaoSenior, inscricao=inscricao)
    elif evento.tipo == 'juvenil':
        inscricao_base = get_object_or_404(InscricaoJuvenil, inscricao=inscricao)
    elif evento.tipo == 'mirim':
        inscricao_base = get_object_or_404(InscricaoMirim, inscricao=inscricao)
    else:  # 'servos'
        inscricao_base = get_object_or_404(InscricaoServos, inscricao=inscricao)

    # Adiciona a data de nascimento ao contexto
    data_nascimento = inscricao_base.data_nascimento

    return render(request, 'inscricoes/ficha_inscricao.html', {
        'inscricao': inscricao,
        'inscricao_base': inscricao_base,  # Passa a instância do modelo base
        'data_nascimento': data_nascimento,  # Passa a data de nascimento
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
    evento   = get_object_or_404(EventoAcampamento, slug=slug)
    politica = PoliticaPrivacidade.objects.first()
    hoje = dj_tz.localdate()

    # —> Se hoje estiver fora do período de inscrições, exibe template de encerradas
    if hoje < evento.inicio_inscricoes or hoje > evento.fim_inscricoes:
        return render(request, 'inscricoes/inscricao_encerrada.html', {
            'evento': evento,
            'politica': politica
        })

    if 'participante_id' in request.session:
        # Usuário já preencheu o formulário inicial
        endereco_form = ParticipanteEnderecoForm(request.POST or None)
        if request.method == 'POST' and endereco_form.is_valid():
            participante = Participante.objects.get(id=request.session['participante_id'])
            participante.CEP      = endereco_form.cleaned_data['CEP']
            participante.endereco = endereco_form.cleaned_data['endereco']
            participante.numero   = endereco_form.cleaned_data['numero']
            participante.bairro   = endereco_form.cleaned_data['bairro']
            participante.cidade   = endereco_form.cleaned_data['cidade']
            participante.estado   = endereco_form.cleaned_data['estado']
            participante.save()

            del request.session['participante_id']

            inscricao = Inscricao.objects.get(participante=participante, evento=evento)
            return redirect('inscricoes:formulario_personalizado', inscricao_id=inscricao.id)

        return render(request, 'inscricoes/inscricao_inicial.html', {
            'endereco_form': endereco_form,
            'evento': evento,
            'politica': politica
        })

    else:
        # Exibir o formulário inicial
        inicial_form = ParticipanteInicialForm(request.POST or None)
        if request.method == 'POST' and inicial_form.is_valid():
            cpf = ''.join(filter(str.isdigit, inicial_form.cleaned_data['cpf']))
            participante, created = Participante.objects.get_or_create(
                cpf=cpf,
                defaults={
                    'nome': inicial_form.cleaned_data['nome'],
                    'email': inicial_form.cleaned_data['email'],
                    'telefone': inicial_form.cleaned_data['telefone']
                }
            )
            if not created:
                participante.nome     = inicial_form.cleaned_data['nome']
                participante.email    = inicial_form.cleaned_data['email']
                participante.telefone = inicial_form.cleaned_data['telefone']
                participante.save()

            request.session['participante_id'] = participante.id

            inscricao_existente = Inscricao.objects.filter(
                participante=participante,
                evento=evento
            ).first()

            if inscricao_existente:
                form_map = {
                    'senior':  'inscricaosenior',
                    'juvenil': 'inscricaojuvenil',
                    'mirim':   'inscricaomirim',
                    'servos':  'inscricaoservos',
                }
                rel_name = form_map.get(evento.tipo.lower())
                if rel_name and getattr(inscricao_existente, rel_name, None):
                    return redirect('inscricoes:ver_inscricao', pk=inscricao_existente.id)
                return redirect('inscricoes:formulario_personalizado', inscricao_id=inscricao_existente.id)

            try:
                inscricao = Inscricao.objects.create(
                    participante=participante,
                    evento=evento,
                    paroquia=evento.paroquia
                )
            except IntegrityError:
                inscricao = Inscricao.objects.get(participante=participante, evento=evento)
                return redirect('inscricoes:ver_inscricao', pk=inscricao.id)

            return redirect('inscricoes:inscricao_inicial', slug=evento.slug)

        return render(request, 'inscricoes/inscricao_inicial.html', {
            'form': inicial_form,
            'evento': evento,
            'politica': politica
        })
    
    
def buscar_participante_ajax(request):
    cpf = request.GET.get('cpf', '').replace('.', '').replace('-', '')
    evento_id = request.GET.get('evento_id')
    print(f"[AJAX] CPF recebido no servidor: {cpf}, evento_id: {evento_id}")

    try:
        participante = Participante.objects.get(cpf=cpf)

        # só considera inscrição se for neste mesmo evento
        inscricao = None
        if evento_id:
            inscricao = Inscricao.objects.filter(
                participante=participante,
                evento_id=evento_id
            ).first()

        if inscricao:
            return JsonResponse({
                'ja_inscrito': True,
                'inscricao_id': inscricao.id
            })

        # participa mas não neste evento, devolve dados para auto-preenchimento
        return JsonResponse({
            'ja_inscrito': False,
            'nome': participante.nome,
            'email': participante.email,
            'telefone': participante.telefone
        })

    except Participante.DoesNotExist:
        return JsonResponse({'ja_inscrito': False})

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'error': 'Erro interno: ' + str(e)}, status=500)
    

def formulario_personalizado(request, inscricao_id):
    # Obtém a inscrição, evento e política de privacidade
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    politica = PoliticaPrivacidade.objects.first()

    # Mapeia tipo de evento → (FormClass, atributo OneToOne na Inscricao)
    form_map = {
        'senior':  (InscricaoSeniorForm, 'inscricaosenior'),
        'juvenil': (InscricaoJuvenilForm, 'inscricaojuvenil'),
        'mirim':   (InscricaoMirimForm, 'inscricaomirim'),
        'servos':  (InscricaoServosForm, 'inscricaoservos'),
    }
    tipo = evento.tipo.lower()
    if tipo not in form_map:
        raise Http404("Tipo de evento inválido.")

    FormClass, rel_name = form_map[tipo]
    instancia = getattr(inscricao, rel_name, None)
    conj_inst = getattr(inscricao, 'conjuge', None)

    if request.method == 'POST':
        form       = FormClass(request.POST, request.FILES, instance=instancia)
        conj_form  = ConjugeForm(request.POST, instance=conj_inst)
        if form.is_valid() and conj_form.is_valid():
            # Salva dados do formulário principal
            obj = form.save(commit=False)
            obj.inscricao = inscricao
            obj.save()

            # Salva dados do Conjuge
            conj = conj_form.save(commit=False)
            conj.inscricao = inscricao
            conj.save()

            return redirect('inscricoes:formulario_contato', inscricao_id=inscricao.id)
    else:
        form      = FormClass(instance=instancia)
        conj_form = ConjugeForm(instance=conj_inst)

    # Campos que o JS vai mostrar/ocultar
    campos_condicionais = [
        'nome_conjuge',
        'casado_na_igreja',
        'conjuge_inscrito',
        'ja_e_campista',
    ]

    return render(request, 'inscricoes/formulario_personalizado.html', {
        'form':               form,
        'conj_form':          conj_form,
        'inscricao':          inscricao,
        'evento':             evento,
        'campos_condicionais':campos_condicionais,
        'politica':           politica,
    })


def formulario_contato(request, inscricao_id):
    # Recupera a inscrição com base no ID
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)

    # Recupera o evento associado à inscrição
    evento = inscricao.evento

    # Recupera a política de privacidade
    politica = PoliticaPrivacidade.objects.first()

    if request.method == 'POST':
        form = ContatoForm(request.POST)
        if form.is_valid():
            # Processar os dados do formulário
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

            # Salvar a instância da inscrição
            inscricao.save()

            # Redireciona para o formulário de dados de saúde
            return redirect('inscricoes:formulario_saude', inscricao_id=inscricao.id)
    else:
        # Inicializa o formulário com os dados existentes da inscrição
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

    return render(request, 'inscricoes/formulario_contato.html', {
        'form': form,
        'inscricao': inscricao,
        'evento': evento,
        'politica': politica,
    })

def formulario_saude(request, inscricao_id):
    inscricao = get_object_or_404(Inscricao, id=inscricao_id)
    evento = inscricao.evento
    participante = inscricao.participante
    politica = PoliticaPrivacidade.objects.first()

    # Seleciona a instância correta de BaseInscricao
    if evento.tipo == 'senior':
        base_inscricao = get_object_or_404(InscricaoSenior, inscricao=inscricao)
    elif evento.tipo == 'juvenil':
        base_inscricao = get_object_or_404(InscricaoJuvenil, inscricao=inscricao)
    elif evento.tipo == 'mirim':
        base_inscricao = get_object_or_404(InscricaoMirim, inscricao=inscricao)
    else:
        base_inscricao = get_object_or_404(InscricaoServos, inscricao=inscricao)

    if request.method == 'POST':
        form_saude = DadosSaudeForm(request.POST, request.FILES, instance=base_inscricao)

        # Lê a decisão do modal (hidden no template)
        consent_ok = (request.POST.get('consentimento_envio') == 'sim')
        if not consent_ok:
            form_saude.add_error(None, "Você precisa aceitar a Política de Privacidade para enviar a inscrição.")

        if form_saude.is_valid():
            # Salva todos os campos, inclusive a foto anexada ao form/base_inscricao
            obj = form_saude.save()

            # Se enviou foto no form, sincroniza no Participante
            foto = form_saude.cleaned_data.get('foto')
            if foto:
                participante.foto = foto
                participante.save(update_fields=['foto'])

            # Marca opt-in de marketing se aceitou no modal
            if consent_ok:
                prefs, _ = PreferenciasComunicacao.objects.get_or_create(participante=participante)
                if not prefs.whatsapp_marketing_opt_in:
                    ip = request.META.get('REMOTE_ADDR')
                    ua = request.META.get('HTTP_USER_AGENT')
                    prova = f"IP={ip} | UA={ua} | ts={timezone.now().isoformat()}"
                    # usa o método helper do modelo (se você criou) ou seta os campos manualmente:
                    try:
                        prefs.marcar_optin_marketing(fonte='form', prova=prova, versao='v1')
                    except AttributeError:
                        # fallback caso não tenha o método marcar_optin_marketing
                        prefs.whatsapp_marketing_opt_in = True
                        prefs.whatsapp_optin_data = timezone.now()
                        prefs.whatsapp_optin_fonte = 'form'
                        prefs.whatsapp_optin_prova = prova
                        prefs.politica_versao = 'v1'
                        prefs.save()

            # Marca inscrição como enviada (dispara e-mails/WhatsApp se seu modelo tratar no save)
            if not inscricao.inscricao_enviada:
                inscricao.inscricao_enviada = True
                inscricao.save(update_fields=['inscricao_enviada'])

            messages.success(request, "Dados de saúde enviados com sucesso.")
            return redirect('inscricoes:ver_inscricao', pk=inscricao.id)
        else:
            # Para debug, imprime erros no console
            print("Erros no DadosSaudeForm:", form_saude.errors)

    else:
        # GET: carrega o form com os dados já salvos
        form_saude = DadosSaudeForm(instance=base_inscricao)

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

def relatorio_crachas(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    cidade_selecionada = request.GET.get('cidade', '')

    # 1) Só inscrições concluídas
    inscricoes = Inscricao.objects.filter(
        evento=evento,
        inscricao_concluida=True
    ).select_related(
        'participante',
        'paroquia',
        'inscricaosenior',
        'inscricaojuvenil',
        'inscricaomirim',
        'inscricaoservos'
    )

    # 2) Filtro por cidade do participante
    if cidade_selecionada:
        inscricoes = inscricoes.filter(participante__cidade=cidade_selecionada)

    # 3) Lista de cidades únicas para o dropdown
    cidades = inscricoes.values_list('participante__cidade', flat=True).distinct().order_by('participante__cidade')

    # 4) Template de crachá
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

    # 1) Buscar as inscrições para o evento
    inscricoes = Inscricao.objects.filter(evento=evento)

    # 2) Aplicar filtros de cidade, status e seleção
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

    # 3) Extrair participantes distintos
    participantes = Participante.objects.filter(inscricao__in=inscricoes).distinct()

    # 4) Lista de cidades
    cidades = participantes.values_list('cidade', flat=True).distinct().order_by('cidade')

    # 5) Buscar de fato as inscrições (para carregamento de OneToOne)
    inscricoes_qs = inscricoes.select_related(
        'inscricaosenior', 'inscricaojuvenil', 'inscricaomirim', 'inscricaoservos'
    )

    # 6) Montar dict para lookup no template
    inscricoes_dict = { i.participante_id: i for i in inscricoes_qs }

    # 7) Contagem de camisas
    # chaves devem bater com o template (minúsculas)
    tamanhos = ['PP','P','M','G','GG','XG','XGG']
    quantidades_camisas = { t.lower(): 0 for t in tamanhos }

    for inscr in inscricoes_qs:
        # para cada tipo, tenta buscar o objeto relacionado
        for rel in ('inscricaosenior','inscricaojuvenil','inscricaomirim','inscricaoservos'):
            obj = getattr(inscr, rel, None)
            if obj:
                size = (obj.tamanho_camisa or '').upper()
                key = size.lower()
                if key in quantidades_camisas:
                    quantidades_camisas[key] += 1
                break  # não precisa verificar as outras relações

    return render(request, 'inscricoes/relatorio_inscritos.html', {
        'evento': evento,
        'participantes': participantes,
        'cidades': cidades,
        'inscricoes_dict': inscricoes_dict,
        'cidade_filtro': cidade_filtro,
        'status_filtro': status_filtro,
        'selecionado_filtro': selecionado_filtro,
        'quantidades_camisas': quantidades_camisas,
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

@login_required
def relatorio_ficha_cozinha(request, evento_id):
    evento = get_object_or_404(EventoAcampamento, id=evento_id)
    if not request.user.is_superuser and evento.paroquia != getattr(request.user, 'paroquia', None):
        return HttpResponseForbidden()
    # TODO: implementar geração da ficha de cozinha
    return HttpResponse(f"Ficha de cozinha para {evento.nome}")

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

from decimal import Decimal
from django.db.models import Sum, Count
from django.utils.dateparse import parse_date
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
import csv

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