###############################################################################
# Development settings — imported automatically by manage.py.
# Extends base.py with dev-only tools.
###############################################################################

from .base import *  # pylint: disable=wildcard-import, unused-wildcard-import

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True
SECURE_SSL_REDIRECT = False

# Dev-safe encryption keys — do NOT use in production
SECURED_FIELDS_KEY = os.environ.get(
    "SECURED_FIELDS_KEY", "Ot1ee8MohgGosTKeen8XKKnRsgcwHANhfO3I4Y-0PPc="
)
SECURED_FIELDS_HASH_SALT = os.environ.get("SECURED_FIELDS_HASH_SALT", "8d352777")
