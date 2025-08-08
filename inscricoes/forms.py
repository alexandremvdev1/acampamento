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
        ('sim', 'Sim'),
        ('nao', 'Não'),
    ]

    ESTADO_CIVIL_CHOICES = [
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
    ]

    estado_civil = forms.ChoiceField(
        choices=ESTADO_CIVIL_CHOICES,
        label="Estado Civil",
        widget=forms.Select(attrs={'id': 'id_estado_civil'})
    )

    nome_conjuge = forms.CharField(
        label="Nome do Cônjuge",
        required=False,  # Não obrigatório a princípio
        widget=forms.TextInput(attrs={'id': 'id_nome_conjuge'})
    )

    def clean_nome_conjuge(self):
        nome = self.cleaned_data.get('nome_conjuge', '')
        return nome.title() if nome else nome

    conjuge_inscrito = forms.ChoiceField(
        label="Cônjuge Inscrito?",
        required=False,
        choices=SIM_NAO_CHOICES,
        widget=forms.Select(attrs={'id': 'id_conjuge_inscrito'})
    )

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Inicialmente, torne os campos condicionais não obrigatórios
        self.fields['nome_conjuge'].required = False
        self.fields['conjuge_inscrito'].required = False



class InscricaoSeniorForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoSenior
        fields = [
            "data_nascimento", "batizado", "estado_civil", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]


class InscricaoJuvenilForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoJuvenil
        fields = [
            "data_nascimento", "batizado", "estado_civil", "casado_na_igreja", "nome_conjuge",
            "conjuge_inscrito", "indicado_por", "tamanho_camisa", "paroquia",
            "pastoral_movimento", "outra_pastoral_movimento", "dizimista", "crismado",
            "altura", "peso", "problema_saude", "qual_problema_saude",
            "medicamento_controlado", "qual_medicamento_controlado"
        ]


class InscricaoMirimForm(BaseInscricaoForm):
    class Meta(BaseInscricaoForm.Meta):
        model = InscricaoMirim
        fields = [
            "data_nascimento", "batizado", "estado_civil", "casado_na_igreja", "nome_conjuge",
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
        fields = ['texto', 'imagem_camisa', 'imagem_1', 'imagem_2']
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



class VideoEventoForm(forms.ModelForm):
    class Meta:
        model = VideoEventoAcampamento
        fields = ['titulo', 'arquivo']

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
    class Meta:
        model = Inscricao
        fields = [
            'evento',
            'paroquia',
            'participante',
            'foi_selecionado',
            'pagamento_confirmado',
            'inscricao_concluida',
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
    class Meta:
        model = Conjuge
        fields = ['nome', 'conjuge_inscrito', 'ja_e_campista']
