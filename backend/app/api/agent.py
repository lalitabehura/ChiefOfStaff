from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.core.security import utcnow
from app.db import get_db
from app.deps import get_current_user, get_preferences
from app.models import AgentAction, AgentMessage, Preferences, User
from app.schemas import (
    ActionOut,
    ApproveIn,
    ChatIn,
    ChatOut,
    EmailOut,
    EventOut,
    MessageOut,
    TaskOut,
)
from app.services import actions, audit
from app.services.agent import chat
from app.services.brief import build_brief
from app.services.learning import record_action_decision

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatOut, dependencies=[Depends(rate_limit("chat", 20, 60))])
def agent_chat(body: ChatIn, user: User = Depends(get_current_user),
               prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    reply, created = chat(db, user, prefs, body.message)
    db.commit()
    return ChatOut(reply=reply, actions=[ActionOut.model_validate(a) for a in created])


@router.get("/messages", response_model=list[MessageOut])
def messages(limit: int = Query(default=50, ge=1, le=200), user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentMessage).where(AgentMessage.user_id == user.id)
                      .order_by(AgentMessage.created_at.desc()).limit(limit)).all()
    return rows[::-1]


@router.delete("/messages", status_code=204)
def clear_messages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for m in db.scalars(select(AgentMessage).where(AgentMessage.user_id == user.id)).all():
        db.delete(m)
    db.commit()


@router.get("/actions", response_model=list[ActionOut])
def list_actions(status: str | None = Query(default="pending", pattern="^(pending|executed|rejected|failed|all)$"),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(AgentAction).where(AgentAction.user_id == user.id)
    if status and status != "all":
        stmt = stmt.where(AgentAction.status == status)
    return db.scalars(stmt.order_by(AgentAction.created_at.desc()).limit(200)).all()


def _owned_pending(db: Session, user: User, action_id: str) -> AgentAction:
    a = db.get(AgentAction, action_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(status_code=404, detail="Action not found")
    if a.status != "pending":
        raise HTTPException(status_code=409, detail=f"Action is already {a.status}")
    return a


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
def approve(action_id: str, body: ApproveIn, request: Request, user: User = Depends(get_current_user),
            prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    a = _owned_pending(db, user, action_id)
    edited = False
    if body.payload is not None:
        try:
            new_payload = actions.validate_payload(a.kind, body.payload)
        except actions.ActionRejected as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        edited = new_payload != a.payload
        a.payload = new_payload
    a.decided_at = utcnow()
    audit.record(db, "agent.approved", user.id, request, action_id=a.id, kind=a.kind, edited=edited)
    actions.execute(db, user, a)
    record_action_decision(db, prefs, a.kind, approved=True, edited=edited)
    db.commit()
    return a


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject(action_id: str, request: Request, user: User = Depends(get_current_user),
           prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    a = _owned_pending(db, user, action_id)
    a.status, a.decided_at = "rejected", utcnow()
    record_action_decision(db, prefs, a.kind, approved=False, edited=False)
    audit.record(db, "agent.rejected", user.id, request, action_id=a.id, kind=a.kind)
    db.commit()
    return a


@router.get("/brief")
def brief(user: User = Depends(get_current_user), prefs: Preferences = Depends(get_preferences),
          db: Session = Depends(get_db)):
    b = build_brief(db, user, prefs)
    db.commit()
    return {
        **{k: v for k, v in b.items() if k not in ("events", "top_tasks", "emails_needing_reply")},
        "events": [EventOut.model_validate(e) for e in b["events"]],
        "top_tasks": [TaskOut.model_validate(t) for t in b["top_tasks"]],
        "emails_needing_reply": [EmailOut.model_validate(e) for e in b["emails_needing_reply"]],
    }
