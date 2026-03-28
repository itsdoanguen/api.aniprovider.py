import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR.parent / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "core",
    "anime",
]

# Only include drf_spectacular in development
if DEBUG:
    INSTALLED_APPS.insert(8, "drf_spectacular")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestIDMiddleware",
]

ROOT_URLCONF = "aniprovider_api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "aniprovider_api.wsgi.application"
ASGI_APPLICATION = "aniprovider_api.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", "db.sqlite3"),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", ""),
    }
}

if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    mysql_options = {}
    db_options_charset = os.getenv("DB_OPTIONS_CHARSET", "").strip()
    db_init_command = os.getenv("DB_INIT_COMMAND", "").strip()

    if db_options_charset:
        mysql_options["charset"] = db_options_charset
    if db_init_command:
        mysql_options["init_command"] = db_init_command

    if mysql_options:
        DATABASES["default"]["OPTIONS"] = mysql_options

if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    db_name = DATABASES["default"]["NAME"]
    if db_name and not os.path.isabs(db_name):
        DATABASES["default"]["NAME"] = str(BASE_DIR / db_name)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "aniprovider-cache",
    }
}

REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "core.exceptions.global_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("ANIPROVIDER_API_RATE_LIMIT", "100/min"),
    },
}

# Only enable schema generation in development
if DEBUG:
    REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"

# Only configure Swagger/docs in development
if DEBUG:
    SPECTACULAR_SETTINGS = {
        "TITLE": "AniProvider API",
        "DESCRIPTION": "API for anime episode catalog and streaming sources",
        "VERSION": "1.0.0",
        "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
        "SCHEMA_PATH_PREFIX": r"/api",
        "TAGS_SORTER": "alpha",
        "SWAGGER_UI_SETTINGS": {
            "persistAuthorization": True,
        },
        "APPEND_COMPONENTS": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                }
            }
        },
        "SECURITY": [{"ApiKeyAuth": []}],
    }
else:
    SPECTACULAR_SETTINGS = {}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ANIPROVIDER_CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CORS_ALLOW_ALL_ORIGINS = os.getenv("ANIPROVIDER_CORS_ALLOW_ALL", "false").lower() == "true"

if not DEBUG:
    CORS_ALLOW_ALL_ORIGINS = False

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "true").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "true").lower() == "true"
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_SECURE_HSTS_PRELOAD", "false").lower() == "true"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","request_id":"%(request_id)s","message":"%(message)s"}'
        }
    },
    "filters": {
        "request_id": {"()": "core.logging_filters.RequestIDLogFilter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "120"))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "90"))

ANIPROVIDER_ENABLE_ASYNC_CRAWL = os.getenv("ANIPROVIDER_ENABLE_ASYNC_CRAWL", "false").lower() == "true"
ANIPROVIDER_REQUIRE_REDIS_READY = os.getenv("ANIPROVIDER_REQUIRE_REDIS_READY", "false").lower() == "true"

ANIPROVIDER_EPISODE_TTL_SECONDS = int(os.getenv("ANIPROVIDER_EPISODE_TTL_SECONDS", "600"))
ANIPROVIDER_SOURCE_TTL_SECONDS = int(os.getenv("ANIPROVIDER_SOURCE_TTL_SECONDS", "600"))
ANIPROVIDER_UPSTREAM_BASE_URL = os.getenv("ANIPROVIDER_UPSTREAM_BASE_URL", "https://9animetv.to")
ANIPROVIDER_UPSTREAM_TIMEOUT_SECONDS = int(os.getenv("ANIPROVIDER_UPSTREAM_TIMEOUT_SECONDS", "20"))
ANIPROVIDER_UPSTREAM_RETRY_COUNT = int(os.getenv("ANIPROVIDER_UPSTREAM_RETRY_COUNT", "2"))
ANIPROVIDER_API_KEY = os.getenv("ANIPROVIDER_API_KEY", "")
