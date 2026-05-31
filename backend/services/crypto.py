import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import settings


def _fernet() -> Fernet:
    secret = settings.broker_token_encryption_key or settings.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return value
