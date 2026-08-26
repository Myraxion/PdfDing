from .dev import *  # noqa: F401 F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'BACKUP_NAME': DATA_DIR / 'db' / 'backup.sqlite3',  # noqa: F405
    }
}

# using a simple hasher will reduce test runtime a lot
PASSWORD_HASHERS = ("django.contrib.auth.hashers.MD5PasswordHasher",)
