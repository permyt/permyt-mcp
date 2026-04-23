import os

from pathlib import Path

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "false").lower() in ("true", "1", "yes")
TEST = False

# SECURITY WARNING: keep the secret key used in production secret!
# The "django-insecure-" prefix triggers Django's W009 security check in production.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-do-not-use-in-production",
)

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
SESSION_COOKIE_NAME = "permyt-mcp"

# Security headers (effective when DEBUG=False)
if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Default primary key field type
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Application definition

INSTALLED_APPS = [
    # Django default apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    # Project apps
    "app",
    "app.common",
    "app.common.pages",
    # Core
    "app.core.requests",
    "app.core.users",
    # MCP
    "app.mcp",
    # Auth tokens
    "app.core.users.authtoken",
    # 3rd-party apps
    "axes",
    "corsheaders",
    "rest_framework",
    "secured_fields",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "app.utils.middleware.ThreadLocalUserMiddleware",
    # AxesMiddleware should be the last middleware in the MIDDLEWARE list.
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",
    "django.contrib.auth.backends.ModelBackend",
]


ROOT_URLCONF = "app.urls"
ASGI_APPLICATION = "settings.asgi.application"
WSGI_APPLICATION = "settings.wsgi.application"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# Django REST Framework
# https://www.django-rest-framework.org/

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "app.utils.renderers.JSONRenderer",
        "rest_framework.renderers.AdminRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "app.utils.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/minute",
        "user": "120/minute",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
}

# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    },
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_USER_MODEL = "users.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Axes settings
# https://django-axes.readthedocs.io/en/latest/configuration.html

AXES_FAILURE_LIMIT = 15
AXES_COOLOFF_TIME = 2  # in hours

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "propagate": True,
            "level": "INFO" if DEBUG else "ERROR",
        },
        "console": {
            "handlers": ["console"],
            "level": os.getenv("DJANGO_LOG_LEVEL", "DEBUG"),
        },
    },
}


# CORS
# https://github.com/adamchainz/django-cors-headers

CORS_ALLOW_ALL_ORIGINS = DEBUG


# Secured Fields: https://github.com/C0D1UM/django-secured-fields

SECURED_FIELDS_KEY = os.environ.get("SECURED_FIELDS_KEY", "")
SECURED_FIELDS_HASH_SALT = os.environ.get("SECURED_FIELDS_HASH_SALT", "")


# ---------------------------------------------------------------------------
# PERMYT connector settings
# ---------------------------------------------------------------------------

PERMYT_SERVICE_ID = os.environ.get("PERMYT_SERVICE_ID", "")
PERMYT_PUBLIC_KEY_PATH = os.environ.get("PERMYT_PUBLIC_KEY_PATH", "keys/permyt/public.pem")
PRIVATE_KEY_PATH = os.environ.get("PRIVATE_KEY_PATH", "keys/connector/private.pem")

BASE_URL = os.environ.get("BASE_URL", "https://mcp.permyt.io")
NONCE_TTL_SECONDS = int(os.environ.get("NONCE_TTL_SECONDS", "60"))

PERMYT_HOST = os.environ.get("PERMYT_HOST", "https://permyt.io")
REQUESTER_CALLBACK_URL = os.environ.get("REQUESTER_CALLBACK_URL", BASE_URL + "/rest/permyt/inbound")

# MCP OAuth
MCP_ISSUER_URL = os.environ.get("MCP_ISSUER_URL", BASE_URL.rstrip("/") + "/mcp")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", BASE_URL.rstrip("/") + "/mcp")
DISABLE_SSE_DRF_TOKEN = os.environ.get("DISABLE_SSE_DRF_TOKEN", "false").lower() in ("true", "1", "yes")


# Local settings
try:
    from .local import *  # pylint: disable=unused-wildcard-import,wildcard-import
except ImportError:
    pass
