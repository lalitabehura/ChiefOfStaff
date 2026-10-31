import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, utcnow
from app.db import get_db
from app.models import Preferences, RefreshToken, User

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    # Tokens issued before a password change are invalid.
    if payload["iat"] < int(user.password_changed_at.timestamp()):
        raise _UNAUTHORIZED
    # Session (refresh family) must still be live: logout / revoke takes effect immediately.
    live = db.scalar(
        select(RefreshToken.id).where(
            RefreshToken.family_id == payload["sid"],
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > utcnow(),
        ).limit(1)
    )
    if live is None:
        raise _UNAUTHORIZED
    request.state.session_id = payload["sid"]
    request.state.user_id = user.id
    return user


def get_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Preferences:
    prefs = db.get(Preferences, user.id)
    if prefs is None:
        prefs = Preferences(user_id=user.id, learned={})
        db.add(prefs)
        db.commit()
    return prefs


def require_xhr(request: Request) -> None:
    """CSRF defence for cookie-authenticated endpoints: browsers cannot send custom headers cross-site
    without a CORS preflight, which our CORS policy rejects."""
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
