from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.core.security import hash_token, new_opaque_token, utcnow
from app.db import get_db
from app.deps import get_current_user
from app.models import CalendarEvent, EmailMessage, Integration, OAuthState, Task, User
from app.schemas import IntegrationOut
from app.services import audit
from app.services.demo import seed_demo
from app.services.providers import google
from app.services.sync import sync_user

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationOut])
def list_integrations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Integration).where(Integration.user_id == user.id)).all()


@router.get("/available")
def available():
    return {"google": google.is_configured(), "demo": True,
            "ai": bool(get_settings().anthropic_api_key)}


@router.post("/google/start", dependencies=[Depends(rate_limit("oauth", 10, 300))])
def google_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not google.is_configured():
        raise HTTPException(status_code=400, detail="Google integration is not configured on this server.")
    state = new_opaque_token()
    verifier, challenge = google.pkce_pair()
    db.execute(delete(OAuthState).where(OAuthState.user_id == user.id))
    db.add(OAuthState(user_id=user.id, state_hash=hash_token(state), code_verifier=verifier,
                      expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    return {"auth_url": google.build_auth_url(state, challenge)}


@router.get("/google/callback", include_in_schema=False)
def google_callback(request: Request, code: str | None = Query(default=None, max_length=2000),
                    state: str | None = Query(default=None, max_length=200),
                    error: str | None = Query(default=None, max_length=200),
                    db: Session = Depends(get_db)):
    """Browser redirect target. The user is identified by the single-use, hashed, expiring `state`
    (CSRF protection for OAuth) and the PKCE verifier bound to it."""
    front = get_settings().frontend_url
    if error or not code or not state:
        return RedirectResponse(f"{front}/settings?integration=cancelled", status_code=303)
    row = db.scalar(select(OAuthState).where(OAuthState.state_hash == hash_token(state)))
    if row is None or row.expires_at <= utcnow():
        return RedirectResponse(f"{front}/settings?integration=invalid_state", status_code=303)
    user_id, verifier = row.user_id, row.code_verifier
    db.delete(row)  # single use
    db.commit()
    try:
        tokens = google.exchange_code(code, verifier)
    except google.ProviderError:
        return RedirectResponse(f"{front}/settings?integration=failed", status_code=303)

    integ = db.scalar(select(Integration).where(Integration.user_id == user_id, Integration.provider == "google"))
    if integ is None:
        integ = Integration(user_id=user_id, provider="google")
        db.add(integ)
    integ.access_token = tokens["access_token"]
    integ.refresh_token = tokens.get("refresh_token") or integ.refresh_token
    integ.expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    integ.scopes = tokens.get("scope", "")
    integ.account_email = tokens.get("email", "")
    integ.status = "active"
    integ.connected_at = utcnow()
    audit.record(db, "integration.connected", user_id, request, provider="google")
    db.commit()
    return RedirectResponse(f"{front}/settings?integration=connected", status_code=303)


@router.post("/demo/connect")
def connect_demo(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = seed_demo(db, user)
    audit.record(db, "integration.connected", user.id, request, provider="demo")
    db.commit()
    return result


@router.post("/sync", dependencies=[Depends(rate_limit("sync", 6, 60))])
def sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = sync_user(db, user)
    db.commit()
    return result


@router.delete("/{provider}", status_code=204)
def disconnect(provider: str, request: Request, purge: bool = False,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    integ = db.scalar(select(Integration).where(Integration.user_id == user.id, Integration.provider == provider))
    if integ is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if provider == "google":
        for tok in (integ.refresh_token, integ.access_token):
            if tok:
                google.revoke(tok)  # revoke at Google, not just locally
    source = provider
    db.delete(integ)
    if purge or provider == "demo":
        is_demo_mail = EmailMessage.external_id.like("demo-%")
        db.execute(delete(EmailMessage).where(
            EmailMessage.user_id == user.id, is_demo_mail if provider == "demo" else ~is_demo_mail))
        db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == user.id, CalendarEvent.source == source))
        if provider == "demo":
            db.execute(delete(Task).where(Task.user_id == user.id, Task.source == "demo"))
    audit.record(db, "integration.disconnected", user.id, request, provider=provider, purge=purge)
    db.commit()
