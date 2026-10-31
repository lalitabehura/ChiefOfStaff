from fastapi import Request
from sqlalchemy.orm import Session

from app.core.rate_limit import client_ip
from app.models import AuditLog

# Keys that must never be written to the audit log.
_REDACT = {"password", "token", "code", "secret", "access_token", "refresh_token", "body"}


def record(db: Session, action: str, user_id: str | None = None, request: Request | None = None, **meta) -> None:
    safe_meta = {k: ("[redacted]" if k in _REDACT else v) for k, v in meta.items()}
    db.add(AuditLog(
        user_id=user_id,
        action=action,
        ip=client_ip(request) if request else "",
        user_agent=(request.headers.get("user-agent", "")[:300] if request else ""),
        meta=safe_meta,
    ))
