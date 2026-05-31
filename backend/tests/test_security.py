from auth.security import create_access_token
from models import User
from services.crypto import decrypt_secret, encrypt_secret


def test_secret_encryption_round_trips_and_changes_value() -> None:
    raw = "kite-access-token"
    encrypted = encrypt_secret(raw)

    assert encrypted != raw
    assert decrypt_secret(encrypted) == raw


def test_decrypt_secret_accepts_legacy_plaintext() -> None:
    assert decrypt_secret("legacy-token") == "legacy-token"


def test_access_token_includes_token_version() -> None:
    user = User(id=7, kite_user_id="AB1234", access_token="x", token_version=3)
    token = create_access_token(user)

    assert isinstance(token, str)
    assert token.count(".") == 2
