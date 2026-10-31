"""Cryptographic primitives: password hashing, tokens, encryption at rest, MFA."""
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Passwords (Argon2id)
# ---------------------------------------------------------------------------
_ph = PasswordHasher()  # argon2id, library defaults follow OWASP guidance
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-real-password")

# Small deny-list; production deployments may add a breached-password check (HIBP k-anonymity).
_COMMON_PASSWORDS = {
    "password1234", "password12345", "123456789012", "qwertyuiop12", "letmein12345",
    "iloveyou1234", "welcome12345", "administrator", "passwordpassword", "changeme1234",
}


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    """Spend the same time as a real verification so login timing does not reveal accounts."""
    verify_password(_DUMMY_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def validate_password_strength(password: str, email: str | None = None) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters.")
    if password.lower() in _COMMON_PASSWORDS or len(set(password)) < 5:
        raise ValueError("Password is too common or too simple.")
    if email and email.split("@")[0].lower() in password.lower() and len(email.split("@")[0]) >= 4:
        raise ValueError("Password must not contain your email name.")
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if classes < 3 and len(password) < 16:
        raise ValueError("Use at least 3 of: lowercase, uppercase, digits, symbols (or 16+ characters).")


# ---------------------------------------------------------------------------
# Access tokens (short-lived JWT) and opaque tokens (refresh / reset)
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, session_id: str) -> tuple[str, int]:
    s = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=s.access_token_ttl_minutes)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "typ": "access",
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256"), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(
        token,
        s.secret_key,
        algorithms=["HS256"],  # explicit allow-list prevents alg confusion
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "sid", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Tokens are stored only as SHA-256 hashes; a DB leak does not leak live tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------------------
# Encryption at rest (AES-256-GCM)
# ---------------------------------------------------------------------------
class Cipher:
    VERSION = "v1"
    AAD = b"chief-of-staff:v1"

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Encryption key must be 32 bytes")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode(), self.AAD)
        return f"{self.VERSION}:" + base64.urlsafe_b64encode(nonce + ct).decode()

    def decrypt(self, token: str) -> str:
        version, _, data = token.partition(":")
        if version != self.VERSION:
            raise ValueError("Unknown ciphertext version")
        raw = base64.urlsafe_b64decode(data.encode())
        return self._aes.decrypt(raw[:12], raw[12:], self.AAD).decode()


@lru_cache
def get_cipher() -> Cipher:
    s = get_settings()
    if s.encryption_key:
        key = base64.urlsafe_b64decode(s.encryption_key.encode())
    else:  # development only (production config validation forbids this)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"cos-dev", info=b"enc").derive(
            s.secret_key.encode()
        )
    return Cipher(key)


# ---------------------------------------------------------------------------
# MFA (TOTP + recovery codes)
# ---------------------------------------------------------------------------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp(secret: str, code: str, last_counter: int) -> int | None:
    """Return the matched time-step counter, or None. Rejects replay of an already-used code."""
    totp = pyotp.TOTP(secret)
    current = totp.timecode(utcnow())
    for counter in (current - 1, current, current + 1):
        if counter > last_counter and hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None


def new_recovery_codes(n: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(n)]
