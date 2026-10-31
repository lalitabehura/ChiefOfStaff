"""Custom column types: timezone-safe datetimes and transparently encrypted text."""
from datetime import datetime, timezone

from sqlalchemy.types import DateTime, Text, TypeDecorator


class UTCDateTime(TypeDecorator):
    """Always stores UTC and always returns timezone-aware datetimes (even on SQLite)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EncryptedText(TypeDecorator):
    """AES-256-GCM encrypted at rest. Used for OAuth tokens, MFA secrets, email bodies and drafts."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect):
        if value is None:
            return None
        from app.core.security import get_cipher

        return get_cipher().encrypt(value)

    def process_result_value(self, value: str | None, dialect):
        if value is None:
            return None
        from app.core.security import get_cipher

        return get_cipher().decrypt(value)
