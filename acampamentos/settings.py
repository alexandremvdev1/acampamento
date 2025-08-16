# acampamentos/settings.py (DESENVOLVIMENTO LOCAL)

from pathlib import Path
import os
import dj_database_url
import cloudinary
import cloudinary.uploader
import cloudinary.api
from decimal import Decimal

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# Segurança / Ambiente (DEV)
# -----------------------------------------------------------------------------
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-insecure-key')
DEBUG = True  # sempre True em desenvolvimento local

# Em DEV usamos HTTP local:
SITE_DOMAIN = os.getenv('SITE_DOMAIN', 'http://localhost:8000')

# ALLOWED_HOSTS: sem "https://", apenas hostnames/IPs
ALLOWED_HOSTS = os.getenv(
    'DJANGO_ALLOWED_HOSTS',
    'localhost,127.0.0.1'
).split(',')

# Sites framework (usado em alguns pontos)
SITE_ID = 1

# Em DEV não forçamos HTTPS/cookies seguros
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # inofensivo em dev
SECURE_SSL_REDIRECT   = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE    = False

# CSRF Trusted Origins: incluir localhost e 127.0.0.1 (http e https)
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'https://localhost:8000',
    'http://127.0.0.1:8000',
    'https://127.0.0.1:8000',
]
# Se usar túnel (ngrok etc.), adicione aqui:
# CSRF_TRUSTED_ORIGINS += ['https://seu-subdominio.ngrok.app']

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
    'storages',  # ok manter; não quebra mesmo sem S3
]

# -----------------------------------------------------------------------------
# Middleware
# -----------------------------------------------------------------------------
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # ok em dev também

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
# Banco de Dados (DEV: SQLite por padrão; se quiser, use DATABASE_URL)
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv('DATABASE_URL', '')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=0, ssl_require=False)
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

# Em DEV, use storage sem manifest para evitar erros sem collectstatic:
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# -----------------------------------------------------------------------------
# Cloudinary (mídia) - DEV com credenciais fixas (NÃO USAR EM PRODUÇÃO)
# -----------------------------------------------------------------------------
cloudinary.config(
    cloud_name="dspmsfjp2",
    api_key="797699566468382",
    api_secret="5u3AC6ig72ZV_CMV44bFsyUyAGI",
    secure=True,
)
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# -----------------------------------------------------------------------------
# E-mail (DEV: console)
# -----------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'webmaster@localhost'

# -----------------------------------------------------------------------------
# WhatsApp Cloud API (toggle e credenciais)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# WhatsApp Cloud API (DEV)
# -----------------------------------------------------------------------------
USE_WHATSAPP = True

# Versão da Graph API (use a que aparece no seu app da Meta)
WHATSAPP_API_VERSION = "v20.0"

# WhatsApp Cloud API
WHATSAPP_API_VERSION = "v20.0"
WHATSAPP_PHONE_NUMBER_ID = "792121183974197"   # Phone number ID
WHATSAPP_WABA_ID         = "1810959279459831"  # WABA ID

# NOVO TOKEN (apenas em DEV; em produção use variável de ambiente)
WHATSAPP_TOKEN = "EAASTcC655rUBPBt2oVkHSCrpdW4UYStnf4MJyOfrBLuLAkvAnLOSV6lLdGPvGGhMY7hXDxJNfWqpZCAPYeKZCtd6VHomTwKbxRZCZBtGFHtr06kFqQJXtGkhJZCq1ENwMwRMLq39hPzfJFODMAWTy13t18YAWuIZB3PkRjif63GdVwpdUMAG84UoUZBPQlzGVjO0yNg8pOpXyUIZAqMieYq5UUb6MMrABAAui43MRzdzswhytG3pfrAKNLbRM44xrbUZD"


# (Opcional) token de verificação do webhook em DEV — defina um qualquer se for usar webhook local
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "dev-verify-token")


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} | {levelname} | {name} | {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": LOG_DIR / "usuarios.log",
            "formatter": "verbose",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",   # <-- handler correto
            "formatter": "verbose",            # <-- usa o formatter acima
        },
    },
    "loggers": {
        "django":          {"handlers": ["file", "console"], "level": "INFO", "propagate": True},
        "django.security": {"handlers": ["file"], "level": "WARNING", "propagate": False},
    },
}


# -----------------------------------------------------------------------------
# Outras configs do app
# -----------------------------------------------------------------------------
FEE_DEFAULT_PERCENT = Decimal("5.0")  # 5% por padrão

# -----------------------------------------------------------------------------
# E-mail (DEV: Gmail)
# -----------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True

# Credenciais do Gmail (crie senha de app em "Segurança" da sua conta)
EMAIL_HOST_USER = 'alexandremv.dev@gmail.com'
EMAIL_HOST_PASSWORD = 'vbzo omms ykvo carb'

DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
