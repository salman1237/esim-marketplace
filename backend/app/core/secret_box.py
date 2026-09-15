"""Symmetric encryption for secrets stored in the database (payment gateway
passwords). The key is derived from SECRET_KEY, so a database dump alone
doesn't reveal them. If SECRET_KEY changes, stored secrets can no longer be
decrypted and must be re-entered - decrypt_secret returns None rather than
raising, so callers can fall back cleanly."""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"db-secret-box:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
