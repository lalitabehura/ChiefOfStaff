from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.db import get_db
from app.deps import get_current_user, get_preferences
from app.models import EmailMessage, Preferences, User
from app.schemas import ActionOut, DraftIn, EmailDetail, EmailOut
from app.services import actions
from app.services.sync import sync_user
from app.services.triage import draft_reply, sender_address, triage_email

router = APIRouter(prefix="/email", tags=["email"])


def _owned(db: Session, user: User, email_id: str) -> EmailMessage:
    e = db.get(EmailMessage, email_id)
    if e is None or e.user_id != user.id:
        raise HTTPException(status_code=404, detail="Email not found")
    return e


@router.get("", response_model=list[EmailOut])
def list_emails(category: str | None = Query(default=None, pattern="^(urgent|action|fyi|newsletter|spam|unsorted)$"),
                needs_reply: bool | None = None, limit: int = Query(default=100, ge=1, le=500),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(EmailMessage).where(EmailMessage.user_id == user.id)
    if category:
        stmt = stmt.where(EmailMessage.category == category)
    if needs_reply is not None:
        stmt = stmt.where(EmailMessage.needs_reply.is_(needs_reply))
    return db.scalars(stmt.order_by(EmailMessage.received_at.desc()).limit(limit)).all()


@router.post("/sync", dependencies=[Depends(rate_limit("sync", 6, 60))])
def sync_now(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = sync_user(db, user)
    db.commit()
    return result


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = _owned(db, user, email_id)
    if not e.is_read:
        e.is_read = True
        db.commit()
    return e


@router.post("/{email_id}/triage", response_model=EmailOut,
             dependencies=[Depends(rate_limit("ai", 30, 60))])
def retriage(email_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    e = _owned(db, user, email_id)
    triage_email(db, user, e)
    db.commit()
    return e


@router.post("/{email_id}/draft", response_model=ActionOut,
             dependencies=[Depends(rate_limit("ai", 30, 60))])
def draft(email_id: str, body: DraftIn, user: User = Depends(get_current_user),
          prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    e = _owned(db, user, email_id)
    to = sender_address(e)
    if not to:
        raise HTTPException(status_code=400, detail="Sender address could not be determined.")
    d = draft_reply(db, user, prefs, e, body.instructions)
    action = actions.propose(db, user, prefs, "send_email", {
        "to": [to], "subject": d.subject, "body": d.body, "in_reply_to_email_id": e.id,
    }, rationale="Reply draft - review before sending", confidence=0.7, source="agent", force_approval=True)
    db.commit()
    return action


@router.post("/{email_id}/to-task", response_model=ActionOut)
def to_task(email_id: str, user: User = Depends(get_current_user),
            prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    e = _owned(db, user, email_id)
    action = actions.propose(db, user, prefs, "create_task", {
        "title": (e.subject or "Follow up on email")[:200],
        "description": f"From: {e.sender}\n\n{(e.body or e.snippet)[:2000]}",
        "importance": 4 if e.category == "urgent" else 3, "tags": ["email"], "source_email_id": e.id,
    }, rationale="Created from email by you", confidence=1.0, source="email", force_approval=True)
    actions.execute(db, user, action)  # user-initiated: execute now
    db.commit()
    return action
