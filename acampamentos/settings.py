# acampamentos/settings.py
from pathlib import Path
import os
import dj_database_url
import cloudinary
import cloudinary.uploader
import cloudinary.api

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# Segurança / Ambiente
# -----------------------------------------------------------------------------
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-fallback-key')
DEBUG = os.getenv('DJANGO_DEBUG', 'False') == 'True'

# Domínio público do site (sempre COM https em produção)
SITE_DOMAIN = os.getenv('SITE_DOMAIN', 'https://eismeaqui.app.br')

# ALLOWED_HOSTS: NUNCA coloque "https://", apenas o host
ALLOWED_HOSTS = os.getenv(
    'DJANGO_ALLOWED_HOSTS',
    'eismeaqui.app.br,www.eismeaqui.app.br,localhost,127.0.0.1'
).split(',')

# Sites framework (opcional, você usa em alguns pontos)
SITE_ID = 1

# Confiança no proxy do Render para detectar HTTPS corretamente
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Redirecionar para HTTPS e cookies seguros quando não estiver em DEBUG
SECURE_SSL_REDIRECT   = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE    = not DEBUG

# CSRF Trusted Origins exige esquema (https://)
# Inclui o SITE_DOMAIN e o www.
_csrf_origin = SITE_DOMAIN.replace('http://', 'https://').rstrip('/')
CSRF_TRUSTED_ORIGINS = list({
    _csrf_origin,
    _csrf_origin.replace('://eismeaqui.', '://www.eismeaqui.'),
})

# -----------------------------------------------------------------------------
# Apps
# -----------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django.contrib.sites',

    'inscricoes',

    # Arquivos e mídia
    'cloudinary',
    'cloudinary_storage',
    'storages',  # ok manter; não quebra mesmo sem usar S3
]

# -----------------------------------------------------------------------------
# Middleware
# -----------------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # antes do Common/Static

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',

    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    'inscricoes.middleware.UserActivityLoggingMiddleware',
]

ROOT_URLCONF = 'acampamentos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],  # adicione pastas personalizadas se quiser
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'acampamentos.wsgi.application'

# -----------------------------------------------------------------------------
# Banco de Dados
# -----------------------------------------------------------------------------
# Render/Produção: defina DATABASE_URL
# Local: cai para SQLite automaticamente
DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=True)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------
AUTH_USER_MODEL = 'inscricoes.User'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# -----------------------------------------------------------------------------
# i18n / TZ
# -----------------------------------------------------------------------------
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Araguaina'
USE_I18N = True
USE_TZ = True

# -----------------------------------------------------------------------------
# Static / Media
# -----------------------------------------------------------------------------
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise (arquivos comprimidos e com manifest)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# -----------------------------------------------------------------------------
# Cloudinary (mídia)
# -----------------------------------------------------------------------------
cloudinary.config(
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME', ''),
    api_key    = os.getenv('CLOUDINARY_API_KEY', ''),
    api_secret = os.getenv('CLOUDINARY_API_SECRET', ''),
    secure     = True,
)
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# -----------------------------------------------------------------------------
# E-mail
# -----------------------------------------------------------------------------
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = 'webmaster@localhost'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    DEFAULT_FROM_EMAIL = EMAIL_HOST_USER or 'no-reply@eismeaqui.app.br'

USE_WHATSAPP = True

# Versão da Graph API (use a que aparece no seu app da Meta)
WHATSAPP_API_VERSION = "v20.0"

# IDs e Token (DADOS SENSÍVEIS – deixe assim só no DEV)
WHATSAPP_PHONE_NUMBER_ID = "792121183974197"      # Identificação do número de telefone
WHATSAPP_WABA_ID         = "1810959279459831"     # Identificação da conta do WhatsApp Business
WHATSAPP_TOKEN = (
    "EAASTcC655rUBPL1mS7bk9bBXds6SZBLRZAVFQ6Qgy613TUZB5hIL2CYAfrCMGsHI1NduM2YO3pNx5fph2QbeUgRpjwBwdis"
    "TZAB8OLAZCwsOCRlYhV0ZCO5QrBIrjGwDMSZBePaEgjB3tA4XHMSM8qVGQUrXckWfgoAxGqSIwu2D4HMOZC6jZBUWn2LpXD"
    "Hp3WFy3nClnUKXK9rnL4mdyigZBOWQdrCkuvwkxZBJtSG4w6HePZALoKUr2SD0Fd4Y4nXfpLlp"
)

# (Opcional) token de verificação do webhook em DEV — defina um qualquer se for usar webhook local
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "dev-verify-token")
# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{asctime} | {levelname} | {name} | {message}', 'style': '{'},
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'usuarios.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG' if DEBUG else 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django':           {'handlers': ['file', 'console'], 'level': 'INFO', 'propagate': True},
        'django.security':  {'handlers': ['file'], 'level': 'WARNING', 'propagate': False},
    },
}

from decimal import Decimal
FEE_DEFAULT_PERCENT = Decimal("5.0")  # 5% por padrão