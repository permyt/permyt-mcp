from .base import *  # pylint: disable=unused-wildcard-import,wildcard-import

DEBUG = True
TEST = True
ALLOWED_HOSTS = ["*"]
SECURE_SSL_REDIRECT = False
MEDIA_ROOT = os.path.join(MEDIA_ROOT, "tests")

# Dev-safe encryption keys for test suite
SECURED_FIELDS_KEY = os.environ.get(
    "SECURED_FIELDS_KEY", "Ot1ee8MohgGosTKeen8XKKnRsgcwHANhfO3I4Y-0PPc="
)
SECURED_FIELDS_HASH_SALT = os.environ.get("SECURED_FIELDS_HASH_SALT", "8d352777")
