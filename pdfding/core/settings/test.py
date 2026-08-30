from .dev import *  # noqa: F401 F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# using a simple hasher will reduce test runtime a lot
PASSWORD_HASHERS = ("django.contrib.auth.hashers.MD5PasswordHasher",)
