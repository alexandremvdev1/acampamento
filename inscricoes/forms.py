from django import forms
from .models import Paroquia, User
from django.core.exceptions import ValidationError
from .models import InscricaoSenior, InscricaoJuvenil, InscricaoMirim, InscricaoServos, Contato, BaseInscricao
from .models import EventoAcampamento
from .models import PoliticaPrivacidade
from .models import Inscricao
from .models import VideoEventoAcampamento  # Certifique-se de importar o modelo Inscricao
from .models import PastoralMovimento
from .models import Conjuge
from .models import MercadoPagoConfig
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User
from .models import InscricaoCasais, InscricaoEvento, InscricaoRetiro, AlocacaoMinisterio

class MercadoPagoConfigForm(forms.ModelForm):
    class Meta:
        model = MercadoPagoConfig
        fields = ['access_token', 'public_key', 'sandbox_mode']
        widgets = {
            'access_token': forms.PasswordInput(render_value=True),
            'public_key': forms.TextInput(),
        }

class ParoquiaForm(forms.ModelForm):
    class Meta:
        model = Paroquia
        fields = ['nome', 'cidade', 'estado', 'responsavel', 'email', 'telefone']
        widgets = {
            'telefone': forms.TextInput(attrs={'placeholder': '(00) 00000-0000'}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@paroquia.com'}),
        }


class UserAdminParoquiaForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Senha'}),
        required=True,
        label="Senha"
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirme a senha'}),
        required=True,
        label="Confirmar senha"
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'tipo_usuario', 'paroquia', 'password', 'password_confirm']
        widgets = {
            'email': forms.EmailInput(attrs={'placeholder': 'seu@email.com'}),
            'username': forms.TextInput(attrs={'placeholder': 'Nome de usuário'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')
        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', "As senhas não conferem.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class ParticipanteInicialForm(forms.Form):
    nome = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'id': 'id_nome', 'placeholder': 'Nome completo'})
    )
    cpf = forms.CharField(
        max_length=14,
        widget=forms.TextInput(attrs={'id': 'id_cpf', 'placeholder': '000.000.000-00'})
    )
    telefone = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={'id': 'id_telefone', 'placeholder': '(00) 00000-0000'})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'id': 'id_email', 'placeholder': 'seuemail@mail.com'})
    )

    def clean_nome(self):
        nome = self.cleaned_data.get('nome', '')
        return nome.title()

    def clean_cpf(self):
        cpf = self.cleaned_data.get('cpf', '')
        return cpf


class ParticipanteEnderecoForm(forms.Form):
    CEP = forms.CharField(
        label="CEP",
        max_length=10,
        widget=forms.TextInput(attrs={'placeholder': '00000-000'})
    )
    endereco = forms.CharField(
        label="Endereço",
        max_length=255,
        widget=forms.TextInput(attrs={'placeholder': 'Rua, Avenida...'})
    )
    numero = forms.CharField(
        label="Número",
        max_length=10,
        widget=forms.TextInput(attrs={'placeholder': 'Número'})
    )
    bairro = forms.CharField(
        label="Bairro",
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Bairro'})
    )
    cidade = forms.CharField(
        label="Cidade",
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Cidade'})
    )
    estado = forms.ChoiceField(
        label="Estado",
        choices=[
            ('AC', 'AC'), ('AL', 'AL'), ('AP', 'AP'), ('AM', 'AM'), ('BA', 'BA'),
            ('CE', 'CE'), ('DF', 'DF'), ('ES', 'ES'), ('GO', 'GO'), ('MA', 'MA'),
            ('MT', 'MT'), ('MS', 'MS'), ('MG', 'MG'), ('PA', 'PA'), ('PB', 'PB'),
            ('PR', 'PR'), ('PE', 'PE'), ('PI', 'PI'), ('RJ', 'RJ'), ('RN', 'RN'),
            ('RS', 'RS'), ('RO', 'RO'), ('RR', 'RR'), ('SC', 'SC'), ('SP', 'SP'),
            ('SE', 'SE'), ('TO', 'TO')
        ]
    )

    def clean_endereco(self):
        endereco = self.cleaned_data.get('endereco', '')
        return endereco.title()

    def clean_bairro(self):
        bairro = self.cleaned_data.get('bairro', '')
        return bairro.title()

    def clean_cidade(self):
        cidade = self.cleaned_data.get('cidade', '')
        return cidade.title()

    def clean_estado(self):
        estado = self.cleaned_data.get('estado', '')
        return estado.upper()


class BaseInscricaoForm(forms.ModelForm):
    SIM_NAO_CHOICES = [
        ('', '---------'),
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    ESTADO_CIVIL_CHOICES = [
        ('', '---------'),
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
    ]

    # Pergunta: Já é campista?
    ja_e_campista = forms.ChoiceField(
        choices=SIM_NAO_CHOICES,
        label="Já é Campista?",
        required=False,
        widget=forms.Select(attrs={'id': 'id_ja_e_campista'})
    )

    # Se sim → Qual tema do acampamento?
    tema_acampamento = forms.CharField(
        label="Qual tema do acampamento que participou?",
        required=False,
        widget=forms.TextInput(attrs={
            'id': 'id_tema_acampamento',
            'placeholder': 'Ex.: Acampamento de Jovens 2023'
        })
    )

    # Estado civil
    estado_civil = forms.ChoiceField(
        choices=ESTADO_CIVIL_CHOICES,
        label="Estado Civil",
        required=False,
        widget=forms.Select(attrs={'id': 'id_estado_civil'})
    )

    # Se casado/união → quanto tempo
    tempo_casado_uniao = forms.CharField(
        label="Tempo de união/casamento",
        required=False,
        widget=forms.TextInput(attrs={
            'id': 'id_tempo_casado_uniao',
            'placeholder': 'Ex.: 5 anos'
        })
    )

    # Se casado/união → casado no religioso?
    casado_na_igreja = forms.ChoiceField(
        choices=SIM_NAO_CHOICES,
        label="Casado no religioso?",
        required=False,
        widget=forms.Select(attrs={'id': 'id_casado_na_igreja'})
    )

    # Nome do cônjuge
    nome_conjuge = forms.CharField(
        label="Nome do Cônjuge",
        required=False,
        widget=forms.TextInput(attrs={'id': 'id_nome_conjuge'})
    )

    # Cônjuge inscrito?
    conjuge_inscrito = forms.ChoiceField(
        label="Cônjuge Inscrito?",
        required=False,
        choices=SIM_NAO_CHOICES,
        widget=forms.Select(attrs={'id': 'id_conjuge_inscrito'})
    )

    class Meta:
        abstract = True

    def clean_nome_conjuge(self):
        nome = self.cleaned_data.get('nome_conjuge', '')
        return nome.title() if nome else nome

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Garantir que os campos condicionais nunca sejam obrigatórios
        for field in [
            'nome_conjuge',
            'conjuge_inscrito',
            'tempo_casado_uniao',
            'tema_acampamento'
        ]:
            if field in self.fields:
                self.fields[field].required = False



class InscricaoSeniorForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoSenior
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]


class InscricaoJuvenilForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoJuvenil
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]


class InscricaoMirimForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoMirim
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]


class InscricaoServosForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoServos
        fields = [
            "data_nascimento", "batizado", "estado_civil", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]

class InscricaoCasaisForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoCasais
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado",
            "protocolo_administracao", "mobilidade_reduzida", "qual_mobilidade_reduzida",
            "alergia_alimento", "qual_alergia_alimento",
            "alergia_medicamento", "qual_alergia_medicamento",
            "tipo_sanguineo", "informacoes_extras",
        ]


class InscricaoEventoForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoEvento
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado",
            "protocolo_administracao", "mobilidade_reduzida", "qual_mobilidade_reduzida",
            "alergia_alimento", "qual_alergia_alimento",
            "alergia_medicamento", "qual_alergia_medicamento",
            "tipo_sanguineo", "informacoes_extras",
        ]


class InscricaoRetiroForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoRetiro
        fields = [
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado",
            "protocolo_administracao", "mobilidade_reduzida", "qual_mobilidade_reduzida",
            "alergia_alimento", "qual_alergia_alimento",
            "alergia_medicamento", "qual_alergia_medicamento",
            "tipo_sanguineo", "informacoes_extras",
        ]

class EventoForm(forms.ModelForm):
    class Meta:
        model = EventoAcampamento
        fields = [
            'nome',
            'tipo',
            'data_inicio',
            'data_fim',
            'inicio_inscricoes',
            'fim_inscricoes',
            'valor_inscricao',
            'slug',
            'paroquia',
            'banner',
        ]
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date'}),
            'data_fim': forms.DateInput(attrs={'type': 'date'}),
            'inicio_inscricoes': forms.DateInput(attrs={'type': 'date'}),
            'fim_inscricoes': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super(EventoForm, self).__init__(*args, **kwargs)

        if hasattr(user, 'paroquia') and user.paroquia:
            # Usuário paroquial: esconde o campo paroquia
            self.fields['paroquia'].widget = forms.HiddenInput()
            self.fields['paroquia'].required = False
        else:
            # Admin geral: mostra lista de paróquias
            self.fields['paroquia'].queryset = Paroquia.objects.all()
            self.fields['paroquia'].required = True


class PoliticaPrivacidadeForm(forms.ModelForm):
    class Meta:
        model = PoliticaPrivacidade
        fields = ['texto', 'imagem_camisa', 'imagem_1', "imagem_ajuda", 'imagem_2']
        widgets = {
            'texto': forms.Textarea(attrs={'rows': 5, 'cols': 40}),
        }

class ContatoForm(forms.Form):
    ESCOLHAS_GRAU_PARENTESCO = [
        ('mae', 'Mãe'),
        ('pai', 'Pai'),
        ('irmao', 'Irmão'),
        ('tio', 'Tio'),
        ('tia', 'Tia'),
        ('outro', 'Outro'),
    ]

    responsavel_1_nome = forms.CharField(max_length=200, required=True, label="Nome")
    responsavel_1_telefone = forms.CharField(max_length=20, required=True, label="Telefone")
    responsavel_1_grau_parentesco = forms.ChoiceField(choices=ESCOLHAS_GRAU_PARENTESCO, required=True, label="Grau de Parentesco")
    responsavel_1_ja_e_campista = forms.BooleanField(required=False, label="Já é Campista?", initial=False)

    responsavel_2_nome = forms.CharField(max_length=200, required=False, label="Nome", widget=forms.TextInput(attrs={'required': False}))
    responsavel_2_telefone = forms.CharField(max_length=20, required=False, label="Telefone", widget=forms.TextInput(attrs={'required': False}))
    responsavel_2_grau_parentesco = forms.ChoiceField(choices=ESCOLHAS_GRAU_PARENTESCO, required=False, label="Grau de Parentesco")
    responsavel_2_ja_e_campista = forms.BooleanField(required=False, label="Já é Campista?", initial=False)

    contato_emergencia_nome = forms.CharField(max_length=200, required=True, label="Nome")
    contato_emergencia_telefone = forms.CharField(max_length=20, required=True, label="Telefone")
    contato_emergencia_grau_parentesco = forms.ChoiceField(choices=ESCOLHAS_GRAU_PARENTESCO, required=True, label="Grau de Parentesco")
    contato_emergencia_ja_e_campista = forms.BooleanField(required=False, label="Já é Campista?", initial=False)

    # Transformações automáticas de nomes para título (João Da Silva)
    def clean_responsavel_1_nome(self):
        nome = self.cleaned_data.get('responsavel_1_nome', '')
        return nome.title()

    def clean_responsavel_2_nome(self):
        nome = self.cleaned_data.get('responsavel_2_nome', '')
        return nome.title() if nome else nome

    def clean_contato_emergencia_nome(self):
        nome = self.cleaned_data.get('contato_emergencia_nome', '')
        return nome.title()


from django import forms
from inscricoes.models import InscricaoSenior

class DadosSaudeForm(forms.ModelForm):
    SIM_NAO_CHOICES = [
        ('', 'Selecione'),
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    TIPO_SANGUINEO_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'), ('NS',  'Não sei'),
    ]

    foto = forms.ImageField(
        label="Foto (Mostre seu melhor ângulo! 😉)",
        required=True
    )
    altura = forms.FloatField(
        label="Altura (m)",
        widget=forms.TextInput(attrs={'placeholder': 'Ex: 1.70'}),
        required=True
    )
    peso = forms.FloatField(
        label="Peso (kg)",
        widget=forms.TextInput(attrs={'placeholder': 'Ex: 50'}),
        required=True
    )

    pressao_alta = forms.ChoiceField(
        label="Tem pressão alta?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    diabetes = forms.ChoiceField(
        label="Tem diabetes?",
        choices=SIM_NAO_CHOICES,
        required=True
    )

    problema_saude = forms.ChoiceField(
        label="Possui algum problema de saúde?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    qual_problema_saude = forms.CharField(
        label="Qual problema de saúde?",
        max_length=255,
        required=False
    )

    medicamento_controlado = forms.ChoiceField(
        label="Usa algum medicamento controlado?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    qual_medicamento_controlado = forms.CharField(
        label="Qual medicamento controlado?",
        max_length=255,
        required=False
    )
    protocolo_administracao = forms.CharField(
        label="Protocolo de administração",
        max_length=255,
        required=False
    )

    mobilidade_reduzida = forms.ChoiceField(
        label="Limitações físicas ou mobilidade reduzida?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    qual_mobilidade_reduzida = forms.CharField(
        label="Detalhe a limitação",
        max_length=255,
        required=False
    )

    # Novos campos de alergia
    alergia_alimento = forms.ChoiceField(
        label="Possui alergia a algum alimento?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    qual_alergia_alimento = forms.CharField(
        label="Qual alimento causa alergia?",
        max_length=255,
        required=False
    )

    alergia_medicamento = forms.ChoiceField(
        label="Possui alergia a algum medicamento?",
        choices=SIM_NAO_CHOICES,
        required=True
    )
    qual_alergia_medicamento = forms.CharField(
        label="Qual medicamento causa alergia?",
        max_length=255,
        required=False
    )

    tipo_sanguineo = forms.ChoiceField(
        label="Tipo sanguíneo",
        choices=TIPO_SANGUINEO_CHOICES,
        required=True
    )

    indicado_por = forms.CharField(
        label="Indicado por",
        max_length=200,
        required=False
    )

    informacoes_extras = forms.CharField(
        label="Informações extras",
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Observações adicionais...'}),
        required=False
    )

    class Meta:
        model = InscricaoSenior  # substituído dinamicamente na view
        fields = [
            'foto', 'altura', 'peso',
            'pressao_alta', 'diabetes',
            'problema_saude', 'qual_problema_saude',
            'medicamento_controlado', 'qual_medicamento_controlado', 'protocolo_administracao',
            'mobilidade_reduzida', 'qual_mobilidade_reduzida',
            'alergia_alimento', 'qual_alergia_alimento',
            'alergia_medicamento', 'qual_alergia_medicamento',
            'tipo_sanguineo', 'indicado_por', 'informacoes_extras',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # adiciona classe Bootstrap e placeholders
        for name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control'})

    def clean(self):
        cleaned = super().clean()

        if cleaned.get('problema_saude') == 'sim' and not cleaned.get('qual_problema_saude'):
            self.add_error('qual_problema_saude', 'Por favor, especifique o problema de saúde.')

        if cleaned.get('medicamento_controlado') == 'sim':
            if not cleaned.get('qual_medicamento_controlado'):
                self.add_error('qual_medicamento_controlado', 'Por favor, especifique o medicamento controlado.')
            if not cleaned.get('protocolo_administracao'):
                self.add_error('protocolo_administracao', 'Por favor, informe o protocolo de administração.')

        if cleaned.get('mobilidade_reduzida') == 'sim' and not cleaned.get('qual_mobilidade_reduzida'):
            self.add_error('qual_mobilidade_reduzida', 'Por favor, detalhe a limitação.')

        # validação de alergias
        if cleaned.get('alergia_alimento') == 'sim' and not cleaned.get('qual_alergia_alimento'):
            self.add_error('qual_alergia_alimento', 'Por favor, especifique o alimento.')

        if cleaned.get('alergia_medicamento') == 'sim' and not cleaned.get('qual_alergia_medicamento'):
            self.add_error('qual_alergia_medicamento', 'Por favor, especifique o medicamento.')

        return cleaned



# inscricoes/forms.py
from django import forms
from .models import VideoEventoAcampamento

class VideoEventoForm(forms.ModelForm):
    class Meta:
        model = VideoEventoAcampamento
        fields = ["titulo", "arquivo"]
        widgets = {
            "titulo": forms.TextInput(attrs={
                "placeholder": "Ex.: Aftermovie Acampamento Juvenil 2025",
                "class": "w-full border rounded px-3 py-2"
            }),
        }

    def clean_arquivo(self):
        f = self.cleaned_data.get("arquivo")
        # Opcional: garantir que é vídeo (quando conteúdo vier via upload padrão)
        # Cloudinary aceita muitos formatos; esse check é só um guard-rail leve.
        if f and hasattr(f, "content_type") and not f.content_type.startswith("video/"):
            raise forms.ValidationError("Envie um arquivo de vídeo válido.")
        return f


from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class AlterarCredenciaisForm(forms.ModelForm):
    password = forms.CharField(label='Nova senha', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'password']


class PastoralMovimentoForm(forms.ModelForm):
    class Meta:
        model = PastoralMovimento
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'placeholder': 'Nome do movimento ou pastoral', 'class': 'form-control'}),
        }

class InscricaoForm(forms.ModelForm):
    # Campo extra para vincular (cônjuge)
    inscricao_pareada = forms.ModelChoiceField(
        queryset=Inscricao.objects.none(),
        required=False,
        label="Vincular com outra inscrição (cônjuge)"
    )

    class Meta:
        model = Inscricao
        fields = [
            'evento',
            'paroquia',
            'participante',
            'foi_selecionado',
            'pagamento_confirmado',
            'inscricao_concluida',
            # NOVO:
            'inscricao_pareada',
            # contatos/responsáveis
            'responsavel_1_nome',
            'responsavel_1_telefone',
            'responsavel_1_grau_parentesco',
            'responsavel_1_ja_e_campista',
            'responsavel_2_nome',
            'responsavel_2_telefone',
            'responsavel_2_grau_parentesco',
            'responsavel_2_ja_e_campista',
        ]
        widgets = {
            'evento': forms.HiddenInput(),
            'paroquia': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        # você pode passar `evento=...` ao instanciar o form, mas se não vier,
        # usamos `self.instance.evento`
        evento = kwargs.pop('evento', None)
        super().__init__(*args, **kwargs)

        ev = evento or getattr(self.instance, 'evento', None)
        qs = Inscricao.objects.none()
        if ev:
            qs = Inscricao.objects.filter(evento=ev)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
        self.fields['inscricao_pareada'].queryset = qs

        # se já houver pareamento (de qualquer lado), pré-carrega no campo
        if self.instance and self.instance.pk:
            par = getattr(self.instance, 'inscricao_pareada', None) or getattr(self.instance, 'pareada_por', None)
            if par and (not self.initial.get('inscricao_pareada')):
                self.initial['inscricao_pareada'] = par.pk

    def clean_inscricao_pareada(self):
        par = self.cleaned_data.get('inscricao_pareada')
        if not par:
            return par

        # não pode parear consigo mesmo
        if self.instance and self.instance.pk and par.pk == self.instance.pk:
            raise ValidationError("Não é possível parear com a própria inscrição.")

        # deve ser do mesmo evento
        ev_id = (self.instance.evento_id if self.instance and self.instance.pk else None) or \
                (self.cleaned_data.get('evento').id if self.cleaned_data.get('evento') else None) or \
                (self.initial.get('evento').id if self.initial.get('evento') else None)
        if ev_id and par.evento_id != ev_id:
            raise ValidationError("A inscrição pareada deve ser do mesmo evento.")

        return par

    def save(self, commit=True):
        obj = super().save(commit=False)
        par = self.cleaned_data.get('inscricao_pareada')

        if commit:
            obj.save()

            # espelha o vínculo nas duas pontas se seu modelo tiver helpers
            if hasattr(obj, 'set_pareada') and hasattr(obj, 'desparear'):
                if par:
                    obj.set_pareada(par)
                else:
                    obj.desparear()
            else:
                # fallback simples (apenas um lado) – ainda funciona com a prop `par`
                obj.inscricao_pareada = par
                obj.save(update_fields=['inscricao_pareada'])

        return obj

from .models import Participante

class ParticipanteForm(forms.ModelForm):
    class Meta:
        model = Participante
        fields = [
            'nome', 'cpf', 'telefone', 'email',
            'CEP', 'endereco', 'numero',
            'bairro', 'cidade', 'estado', 'foto',
        ]
        widgets = {
            'cpf': forms.TextInput(attrs={'placeholder': '000.000.000-00'}),
            'telefone': forms.TextInput(attrs={'placeholder': '(00) 00000-0000'}),
            'CEP': forms.TextInput(attrs={'placeholder': '00000-000'}),
        }


class ConjugeForm(forms.ModelForm):
    SIM_NAO_CHOICES = [
        ('', '---------'),
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    ja_e_campista = forms.ChoiceField(
        label="Cônjuge já é Campista?",
        choices=SIM_NAO_CHOICES,
        required=False,
        widget=forms.Select(attrs={'id': 'id_conj_ja_e_campista'})
    )

    acampamento = forms.CharField(   # 👈 usar o MESMO nome do modelo
        label="Qual tema do acampamento?",
        required=False,
        widget=forms.TextInput(attrs={
            'id': 'id_conj_acampamento',
            'placeholder': 'Ex.: Acampamento Casais 2022'
        })
    )

    class Meta:
        model = Conjuge
        fields = ['nome', 'conjuge_inscrito', 'ja_e_campista', 'acampamento']  # 👈 aqui também

    def clean_nome(self):
        nome = self.cleaned_data.get('nome', '')
        return nome.title() if nome else nome

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('ja_e_campista') == 'sim' and not cleaned.get('acampamento'):
            self.add_error('acampamento', 'Informe o tema do acampamento do cônjuge.')
        return cleaned


from django import forms
from django.forms import modelformset_factory
from .models import Filho

class FilhoForm(forms.ModelForm):
    class Meta:
        model = Filho
        fields = ['nome', 'endereco', 'telefone', 'idade']
        widgets = {
            'nome': forms.TextInput(attrs={
                'placeholder': 'Nome do filho',
                'class': 'form-control',
            }),
            'endereco': forms.TextInput(attrs={
                'placeholder': 'Endereço',
                'class': 'form-control',
            }),
            'telefone': forms.TextInput(attrs={
                'placeholder': '(00) 00000-0000',
                'class': 'form-control',
            }),
            'idade': forms.NumberInput(attrs={
                'min': 0,
                'max': 30,
                'class': 'form-control',
                'placeholder': 'Idade',
            }),
        }
        labels = {
            'nome': 'Nome',
            'endereco': 'Endereço',
            'telefone': 'Telefone',
            'idade': 'Idade',
        }

    def clean_nome(self):
        nome = self.cleaned_data.get('nome', '')
        return nome.title() if nome else nome

FilhoFormSet = modelformset_factory(
    Filho,
    form=FilhoForm,
    extra=0,  # Começa sem filhos visíveis
    can_delete=True
)

# inscricoes/forms.py
from django import forms
from django.utils import timezone
from .models import Pagamento

class PagamentoForm(forms.ModelForm):
    class Meta:
        model = Pagamento
        fields = ["valor", "metodo", "status", "data_pagamento", "comprovante"]
        widgets = {
            "data_pagamento": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        # opcional: receber a inscrição para sugerir valor padrão
        self.inscricao = kwargs.pop("inscricao", None)
        super().__init__(*args, **kwargs)
        if not self.instance.pk and self.inscricao:
            try:
                self.fields["valor"].initial = self.inscricao.evento.valor_inscricao
            except Exception:
                pass

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        data_pg = cleaned.get("data_pagamento")

        # se marcar como confirmado e não informar data, preenche com agora
        if status == Pagamento.StatusPagamento.CONFIRMADO and not data_pg:
            cleaned["data_pagamento"] = timezone.now()
        return cleaned

# forms.py
from django import forms
from .models import PoliticaReembolso

class PoliticaReembolsoForm(forms.ModelForm):
    class Meta:
        model = PoliticaReembolso
        fields = [
            'ativo',
            'permite_reembolso',
            'prazo_solicitacao_dias',
            'taxa_administrativa_percent',
            'descricao',
            'contato_email',
            'contato_whatsapp',
        ]
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 6}),
        }


class AdminParoquiaCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["first_name", "last_name", "username", "email"]  # senha vem do UserCreationForm

    def save(self, commit=True, paroquia=None):
        user = super().save(commit=False)
        user.tipo_usuario = "admin_paroquia"
        if paroquia is not None:
            user.paroquia = paroquia
        if commit:
            user.save()
        return user

# --- Form de contato da landing (/site/) ---
from django import forms

class LeadLandingForm(forms.Form):
    nome = forms.CharField(
        label="Nome",
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "mt-1 block w-full rounded-xl border-slate-300 focus:border-indigo-400 focus:ring-indigo-200",
            "placeholder": "Seu nome completo",
            "required": True,
        }),
    )
    whatsapp = forms.CharField(
        label="WhatsApp",
        max_length=20,
        widget=forms.TextInput(attrs={
            "class": "mt-1 block w-full rounded-xl border-slate-300 focus:border-indigo-400 focus:ring-indigo-200",
            "placeholder": "(xx) xxxxx-xxxx",
            "inputmode": "tel",
            "required": True,
        }),
    )
    email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={
            "class": "mt-1 block w-full rounded-xl border-slate-300 focus:border-indigo-400 focus:ring-indigo-200",
            "placeholder": "voce@paroquia.com",
            "required": True,
        }),
    )
    mensagem = forms.CharField(
        label="Mensagem (opcional)",
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "class": "mt-1 block w-full rounded-xl border-slate-300 focus:border-indigo-400 focus:ring-indigo-200",
            "placeholder": "Conte rapidamente sobre seu evento ou paróquia...",
        }),
    )
    lgpd = forms.BooleanField(
        label="Concordo em ser contatado e com o tratamento dos meus dados conforme a LGPD para fins de atendimento.",
        required=True,
        widget=forms.CheckboxInput(attrs={"class": "mt-1"}),
    )

# inscricoes/forms.py
from django import forms
# ... seus imports ...
from .models import Comunicado

class ComunicadoForm(forms.ModelForm):
    class Meta:
        model = Comunicado
        fields = ["titulo", "texto", "capa", "publicado"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Título"}),
            "texto": forms.Textarea(attrs={"class": "form-control", "rows": 8, "placeholder": "Escreva a publicação..."}),
            "publicado": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

# inscricoes/forms.py
from django import forms
from .models import Ministerio, AlocacaoMinisterio, Inscricao

class MinisterioForm(forms.ModelForm):
    class Meta:
        model = Ministerio
        fields = ["nome", "descricao"]  # evento será setado na view para "novo"

class AlocacaoMinisterioForm(forms.ModelForm):
    class Meta:
        model = AlocacaoMinisterio
        fields = ["inscricao"]  # ministerio será setado na view

    def __init__(self, *args, **kwargs):
        evento = kwargs.pop("evento", None)
        ministerio = kwargs.pop("ministerio", None)
        super().__init__(*args, **kwargs)

        # Limita inscrições ao mesmo evento e que ainda não estejam alocadas neste ministério
        if evento:
            qs = Inscricao.objects.filter(evento=evento)
            if ministerio:
                qs = qs.exclude(alocacao_ministerio__ministerio=ministerio)
            self.fields["inscricao"].queryset = qs.select_related("participante").order_by("participante__nome")

        # Aparência
        for f in self.fields.values():
            f.widget.attrs.update({"class": "form-select"})

from django import forms
from .models import InscricaoCasais


# forms.py

class InscricaoCasaisForm(BaseInscricaoForm):
    # deixa a foto opcional aqui; a view define required=True na etapa 2
    foto_casal = forms.ImageField(
        label="Foto do casal",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/*"})
    )

    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoCasais
        fields = [
            # --- dados básicos ---
            "data_nascimento", "batizado", "estado_civil", "tempo_casado_uniao",
            "casado_na_igreja", "nome_conjuge", "conjuge_inscrito", "indicado_por",
            "tamanho_camisa", "paroquia", "pastoral_movimento", "outra_pastoral_movimento",
            "dizimista", "crismado", "altura", "peso",

            # --- saúde ---
            "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado", "protocolo_administracao",
            "mobilidade_reduzida", "qual_mobilidade_reduzida",
            "alergia_alimento", "qual_alergia_alimento",
            "alergia_medicamento", "qual_alergia_medicamento",
            "diabetes", "pressao_alta",
            "tipo_sanguineo", "informacoes_extras",

            # --- upload da foto (entrada do usuário) ---
            "foto_casal",
        ]
        widgets = {
            "data_nascimento": forms.DateInput(attrs={"type": "date"}),
            "altura": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "peso": forms.NumberInput(attrs={"step": "0.1", "min": "0"}),
            "informacoes_extras": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Aparência padrão bootstrap
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.Textarea, forms.FileInput, forms.DateInput,
                              forms.NumberInput, forms.TextInput, forms.EmailInput, forms.URLInput)):
                css = "form-control"
            elif isinstance(w, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            w.attrs.update({"class": css})

        # limita estado civil
        self.fields["estado_civil"].choices = [
            ("casado", "Casado"),
            ("uniao_estavel", "União Estável"),
        ]
        self.fields["tempo_casado_uniao"].label = "Tempo de união (anos/meses)"


from django.core.exceptions import ValidationError

class FormBasicoPagamentoPublico(forms.Form):
    # Participante 1
    nome = forms.CharField(label="Nome completo (1º participante)", max_length=150)
    cpf = forms.CharField(label="CPF do 1º participante", max_length=18)  # aceita máscara
    # Participante 2 (opcional, mas se informar CPF precisa ter nome, e vice-versa)
    nome_segundo = forms.CharField(
        label="Nome completo (2º participante - opcional)",
        max_length=150,
        required=False
    )
    cpf_segundo = forms.CharField(
        label="CPF do 2º participante (opcional)",
        max_length=18,
        required=False
    )
    # Comum
    cidade = forms.CharField(label="Cidade", max_length=120, required=False)

    def clean_nome(self):
        return (self.cleaned_data.get("nome") or "").strip()

    def clean_nome_segundo(self):
        return (self.cleaned_data.get("nome_segundo") or "").strip()

    def clean_cidade(self):
        return (self.cleaned_data.get("cidade") or "").strip()

    def clean(self):
        data = super().clean()
        nome2 = (data.get("nome_segundo") or "").strip()
        cpf2 = (data.get("cpf_segundo") or "").strip()

        # Se informou CPF2, exige nome2; se informou nome2, exige CPF2
        if cpf2 and not nome2:
            raise ValidationError("Informe o nome do 2º participante.")
        if nome2 and not cpf2:
            raise ValidationError("Informe o CPF do 2º participante.")

        return data
    
class MinisterioForm(forms.ModelForm):
    class Meta:
        model = Ministerio
        fields = ["nome", "descricao"]

    def __init__(self, *args, **kwargs):
        # vamos receber o evento por argumento para validar/atribuir
        self.evento = kwargs.pop("evento", None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.evento:
            obj.evento = self.evento
        if commit:
            obj.save()
        return obj
        
class AlocarInscricaoForm(forms.Form):
    inscricao = forms.ModelChoiceField(
        queryset=Inscricao.objects.none(),
        label="Inscrição do participante",
        required=True,
        help_text="Apenas inscrições deste evento aparecem aqui."
    )

    def __init__(self, *args, **kwargs):
        # >>> Retira os kwargs customizados ANTES do super()
        self.evento: EventoAcampamento | None = kwargs.pop("evento", None)
        self.ministerio: Ministerio | None = kwargs.pop("ministerio", None)

        super().__init__(*args, **kwargs)

        # Define o queryset do campo conforme o evento
        qs = Inscricao.objects.none()
        if self.evento:
            qs = Inscricao.objects.filter(evento=self.evento)
            # Se quiser, filtre por status, por ex.:
            # qs = qs.filter(status__in=["confirmada", "paga", ...])

        self.fields["inscricao"].queryset = qs
        self.fields["inscricao"].label_from_instance = (
            lambda obj: f"{obj.participante.nome} — #{obj.id}"
        )

    def clean(self):
        cleaned = super().clean()
        insc: Inscricao | None = cleaned.get("inscricao")

        if not self.evento:
            raise ValidationError("Evento não informado no formulário.")

        if insc and insc.evento_id != self.evento.id:
            raise ValidationError("A inscrição selecionada não pertence a este evento.")

        # (Opcional) Bloquear duplicidade de alocação nesse ministério/evento
        if self.ministerio and insc:
            existe = AlocacaoMinisterio.objects.filter(
                evento=self.evento,
                ministerio=self.ministerio,
                inscricao=insc,
            ).exists()
            if existe:
                raise ValidationError("Esta inscrição já está alocada neste ministério.")

        return cleaned