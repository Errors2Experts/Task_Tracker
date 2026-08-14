"""
Django settings for task_tracker project.
"""
import os
from pathlib import Path
import dj_database_url
from datetime import timedelta
from decouple import config, Csv
import cloudinary

BASE_DIR = Path(__file__).resolve().parent.parent

# --- SECURITY ---
# All of these read from environment variables / a .env file (see .env.example).
# Sensible defaults are provided ONLY for local development.
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-CHANGE-THIS-FOR-DEV-ONLY-do-not-use-in-production",
)
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = ['.onrender.com','127.0.0.1', 'localhost']
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'django_ckeditor_5',
    'apps.accounts',
    'apps.tasks',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'task_tracker.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.tasks.context_processors.unread_task_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'task_tracker.wsgi.application'

# --- DATABASE ---
# Defaults to SQLite for easy local setup. In production, set these env vars
# to point at PostgreSQL instead (see .env.example).
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'task_tracker',
#         'USER' :'postgres',
#         'PASSWORD' :'suba',
#         'HOST' :'localhost',
#         'PORT' :'5432',
#     }
# }
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = "accounts.User"

LANGUAGE_CODE = 'en-us'
TIME_ZONE = config("TIME_ZONE", default="Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# --- STATIC FILES ---
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # populated by `collectstatic` for production
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- MEDIA (task attachments) ---
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / "media"

# Belt-and-braces cap on upload size at the request level too — matches
# apps.tasks.models.MAX_ATTACHMENT_SIZE_BYTES so an oversized file is
# rejected before Django even fully reads it into memory.
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB

# --- AUTH REDIRECTS ---
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- DJANGO REST FRAMEWORK ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# --- EMAIL ---
# Defaults to printing emails to the console — safe for local dev. Set these
# env vars in production to send real emails (password reset, approval notices).
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@task-tracker.local")

# Used to build absolute "View task" links inside task-created /
# task-completed emails (apps/tasks/emails.py). Set to your real deployed
# URL (e.g. https://your-app.onrender.com) in production.
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000")

# --- PRODUCTION-ONLY SECURITY HARDENING ---
# These only switch on when DEBUG=False (i.e. in a real deployment), so local
# development over plain http:// keeps working without extra setup.
if not DEBUG:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

# --- LOGGING ---
# Errors always go to the console (visible in `runserver`, and captured by
# most hosting platforms/process managers in production).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}

cloudinary.config(
    cloud_name=config("CLOUDINARY_CLOUD_NAME", default=""),
    api_key=config("CLOUDINARY_API_KEY", default=""),
    api_secret=config("CLOUDINARY_API_SECRET", default=""),
    secure=True,
)

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME", default=""),
    "API_KEY": config("CLOUDINARY_API_KEY", default=""),
    "API_SECRET": config("CLOUDINARY_API_SECRET", default=""),
}

VAPID_PUBLIC_KEY = config(
    "VAPID_PUBLIC_KEY",
    default="BHVqVTjk0O8I8MxQBfqw0CBaHjVxh3pPIla_ROeZ5M9hZ4ersUotVgdgFmxjiozLMs-FFoVoyGk15aXxpJK7CFs",
)
VAPID_PRIVATE_KEY = config(
    "VAPID_PRIVATE_KEY",
    default="0MbiJrnTYK66LysUjYeBzofPQKFDXtLErZ4w3zz1Jds",
)
VAPID_CLAIM_EMAIL = config("VAPID_CLAIM_EMAIL", default="admin@task-tracker.local")


# --- CKEDITOR 5 CONFIGURATION ---

CKEDITOR_5_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"  # image upload storage

CKEDITOR_5_CONFIGS = {
    'default': {
        'toolbar': ['heading', '|', 'bold', 'italic', 'link',
                    'bulletedList', 'numberedList', 'blockQuote',
                    'imageUpload', 'insertTable', 'undo', 'redo',
                    'fontColor', 'fontSize', 'codeBlock'],
    },
    'extends': {
        'blockToolbar': [
            'paragraph', 'heading1', 'heading2', 'heading3',
            '|', 'bulletedList', 'numberedList', '|', 'blockQuote',
        ],
        'toolbar': ['heading', '|', 'outdent', 'indent', '|',
                    'bold', 'italic', 'link', 'underline', 'strikethrough',
                    'code', 'subscript', 'superscript', 'highlight', '|',
                    'codeBlock', 'sourceEditing', 'insertImage',
                    'bulletedList', 'numberedList', 'todoList', '|',
                    'blockQuote', 'imageUpload', '|',
                    'fontSize', 'fontFamily', 'fontColor', 'fontBackgroundColor',
                    'mediaEmbed', 'removeFormat', 'insertTable'],
        'image': {
            'toolbar': ['imageTextAlternative', '|', 'imageStyle:alignLeft',
                        'imageStyle:alignRight', 'imageStyle:alignCenter', 'imageStyle:side'],
            'styles': ['full', 'side', 'alignLeft', 'alignRight', 'alignCenter'],
        },
        'table': {
            'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells',
                                'tableProperties', 'tableCellProperties'],
        },
    }
}