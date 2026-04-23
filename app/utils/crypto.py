import secrets

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def generate_token(length, as_hex: bool = False):
    if as_hex:
        return secrets.token_hex(length)
    return secrets.token_urlsafe(length)


def hide_token(token, short: bool = True, chars: int = 3):
    """Mask a token for display, e.g. 'abc***xyz'."""
    if short:
        return f"{token[:chars]}***{token[-chars:]}"
    return f"{token[:chars]}{'*' * (len(token)-chars*2)}{token[-chars:]}"


def generate_es256_pair() -> tuple[str, str]:
    """Generate an ES256 (ECDSA P-256) key pair."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem
