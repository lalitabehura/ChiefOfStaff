"""Profile, preferences, audit log, data export (GDPR Art. 20) and account deletion (Art. 17)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import verify_password
from app.db import get_db
from app.deps import get_current_user, get_preferences
from app.models import (
    USER_OWNED_MODELS,
    AgentAction,
    AgentMessage,
    AuditLog,
    AutomationRule,
    CalendarEvent,
    EmailMessage,
    Integration,
    Preferences,
    Task,
    User,
)
from app.schemas import (
    ActionOut,
    AuditOut,
    DeleteAccountIn,
    EmailDetail,
    EventOut,
    IntegrationOut,
    MessageOut,
    MeUpdate,
    PreferencesIn,
    PreferencesOut,
    RuleOut,
    TaskOut,
    UserOut,
)
from app.services import audit
from app.services.learning import reset_learning

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: MeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for k, v in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return user


@router.get("/preferences", response_model=PreferencesOut)
def get_prefs(prefs: Preferences = Depends(get_preferences)):
    return prefs


@router.put("/preferences", response_model=PreferencesOut)
def put_prefs(body: PreferencesIn, request: Request, user: User = Depends(get_current_user),
              prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    old_autonomy = prefs.autonomy_level
    for k, v in body.model_dump().items():
        setattr(prefs, k, v)
    if old_autonomy != prefs.autonomy_level:
        audit.record(db, "settings.autonomy_changed", user.id, request, old=old_autonomy, new=prefs.autonomy_level)
    db.commit()
    return prefs


@router.post("/preferences/reset-learning", response_model=PreferencesOut)
def reset_learned(user: User = Depends(get_current_user), prefs: Preferences = Depends(get_preferences),
                  db: Session = Depends(get_db)):
    reset_learning(prefs)
    db.commit()
    return prefs


@router.get("/audit-log", response_model=list[AuditOut])
def audit_log(limit: int = Query(default=100, ge=1, le=500), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).where(AuditLog.user_id == user.id)
                      .order_by(AuditLog.created_at.desc()).limit(limit)).all()


@router.get("/export", dependencies=[Depends(rate_limit("export", 3, 3600))])
def export_data(request: Request, response: Response, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    def rows(model, schema):
        return [schema.model_validate(r).model_dump(mode="json")
                for r in db.scalars(select(model).where(model.user_id == user.id)).all()]

    data = {
        "user": UserOut.model_validate(user).model_dump(mode="json"),
        "preferences": PreferencesOut.model_validate(db.get(Preferences, user.id)).model_dump(mode="json")
        if db.get(Preferences, user.id) else None,
        "tasks": rows(Task, TaskOut),
        "events": rows(CalendarEvent, EventOut),
        "emails": rows(EmailMessage, EmailDetail),
        "actions": rows(AgentAction, ActionOut),
        "messages": rows(AgentMessage, MessageOut),
        "rules": rows(AutomationRule, RuleOut),
        "integrations": rows(Integration, IntegrationOut),  # tokens are never exported
        "audit_log": rows(AuditLog, AuditOut),
    }
    audit.record(db, "account.exported", user.id, request)
    db.commit()
    response.headers["Content-Disposition"] = 'attachment; filename="chief-of-staff-export.json"'
    return data


@router.delete("", status_code=204, dependencies=[Depends(rate_limit("delete_account", 5, 3600))])
def delete_account(body: DeleteAccountIn, request: Request, response: Response,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    from app.services.providers import google

    for integ in db.scalars(select(Integration).where(Integration.user_id == user.id)).all():
        if integ.provider == "google" and integ.refresh_token:
            google.revoke(integ.refresh_token)
    for model in USER_OWNED_MODELS:
        db.execute(delete(model).where(model.user_id == user.id))
    user_id = user.id
    db.delete(user)
    # Keep a minimal, anonymised security trail; drop the personal audit history.
    db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
    audit.record(db, "account.deleted", None, request)
    db.commit()
    response.delete_cookie("cos_rt", path="/api/v1/auth")
