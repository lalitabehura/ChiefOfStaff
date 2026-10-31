"""The approval queue and execution policy.

Every side effect - whether suggested by the AI, a rule, or the planner - is an AgentAction.
Payloads are re-validated against strict schemas, ownership of referenced objects is checked,
and outbound communication (email) ALWAYS requires a human approval.
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import (
    AgentAction,
    CalendarEvent,
    EmailMessage,
    Integration,
    Preferences,
    Task,
    User,
)
from app.services import audit
from app.services.providers import google


# --------------------------------------------------------------------------- payload schemas
class CreateTaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    due_at: datetime | None = None
    importance: int = Field(default=3, ge=1, le=5)
    estimate_minutes: int = Field(default=30, ge=5, le=480)
    tags: list[str] = Field(default_factory=list, max_length=10)
    source_email_id: str | None = None


class CompleteTaskPayload(BaseModel):
    task_id: str = Field(max_length=36)
    title: str = Field(default="", max_length=200)  # display only


class CreateEventPayload(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)
    description: str = Field(default="", max_length=5000)
    task_id: str | None = Field(default=None, max_length=36)
    is_focus_block: bool = False

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a timezone offset")
        return self


class SendEmailPayload(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    in_reply_to_email_id: str | None = Field(default=None, max_length=36)

    @field_validator("subject")
    @classmethod
    def _no_header_injection(cls, v: str) -> str:
        if re.search(r"[\r\n]", v):
            raise ValueError("subject must be a single line")
        return v


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "create_task": CreateTaskPayload,
    "complete_task": CompleteTaskPayload,
    "create_event": CreateEventPayload,
    "send_email": SendEmailPayload,
}
ALWAYS_REQUIRE_APPROVAL = {"send_email"}          # outbound communication: never autonomous
LOW_RISK = {"create_task", "complete_task"}       # internal, reversible


class ActionRejected(ValueError):
    pass


def validate_payload(kind: str, payload: dict) -> dict:
    model = PAYLOAD_MODELS.get(kind)
    if model is None:
        raise ActionRejected(f"Unsupported action '{kind}'")
    try:
        return model.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise ActionRejected(f"Invalid {kind} payload: {exc.errors()[0].get('msg', 'invalid')}") from None


def requires_approval(kind: str, autonomy: str) -> bool:
    if kind in ALWAYS_REQUIRE_APPROVAL:
        return True
    if autonomy == "auto":
        return False
    if autonomy == "balanced":
        return kind not in LOW_RISK
    return True  # "suggest": everything is a suggestion


def propose(db: Session, user: User, prefs: Preferences, kind: str, payload: dict, rationale: str,
            confidence: float = 0.6, source: str = "agent", force_approval: bool = False) -> AgentAction:
    clean = validate_payload(kind, payload)
    action = AgentAction(user_id=user.id, kind=kind, payload=clean, rationale=rationale[:500],
                         confidence=max(0.0, min(1.0, confidence)), source=source, status="pending")
    db.add(action)
    db.flush()
    if not force_approval and not requires_approval(kind, prefs.autonomy_level):
        execute(db, user, action, auto=True)
    return action


# --------------------------------------------------------------------------- execution
def _google(db: Session, user_id: str) -> google.GoogleClient | None:
    integ = db.scalar(select(Integration).where(
        Integration.user_id == user_id, Integration.provider == "google", Integration.status == "active"))
    return google.GoogleClient(db, integ) if integ else None


def _owned_task(db: Session, user_id: str, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user_id:  # IDOR protection
        raise ActionRejected("Task not found")
    return task


def execute(db: Session, user: User, action: AgentAction, auto: bool = False) -> AgentAction:
    if action.user_id != user.id:
        raise ActionRejected("Not your action")
    p = validate_payload(action.kind, action.payload)  # re-validate (payload may have been edited)
    try:
        if action.kind == "create_task":
            task = Task(user_id=user.id, title=p["title"], description=p["description"],
                        due_at=datetime.fromisoformat(p["due_at"]) if p["due_at"] else None,
                        importance=p["importance"], estimate_minutes=p["estimate_minutes"],
                        tags=p["tags"], source=action.source if action.source in ("rule", "email") else "agent",
                        source_ref=p.get("source_email_id"))
            db.add(task)
            db.flush()
            from app.services.prioritizer import score_task

            task.priority_score, task.priority_reason = score_task(task, db.get(Preferences, user.id))
            action.result = {"task_id": task.id}

        elif action.kind == "complete_task":
            task = _owned_task(db, user.id, p["task_id"])
            task.status, task.completed_at = "done", utcnow()
            action.result = {"task_id": task.id}

        elif action.kind == "create_event":
            start, end = datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])
            task = _owned_task(db, user.id, p["task_id"]) if p.get("task_id") else None
            client = _google(db, user.id)
            external_id = client.create_event(p["title"], start, end, p["attendees"], p["description"]) if client else None
            ev = CalendarEvent(user_id=user.id, title=p["title"], start=start, end=end,
                               attendees=p["attendees"], description=p["description"],
                               source="google" if client else "agent", external_id=external_id,
                               is_focus_block=p["is_focus_block"], task_id=task.id if task else None)
            db.add(ev)
            if task:
                task.scheduled_start = start
                from app.services.learning import record_scheduled_hour

                prefs = db.get(Preferences, user.id)
                if prefs and not auto:
                    record_scheduled_hour(db, prefs, start.astimezone(ZoneInfo(user.timezone)).hour)
            db.flush()
            action.result = {"event_id": ev.id, "synced_to_google": bool(client)}

        elif action.kind == "send_email":
            if auto:  # defence in depth - policy should already prevent this
                raise ActionRejected("Emails can only be sent after explicit approval")
            original = None
            if p.get("in_reply_to_email_id"):
                original = db.get(EmailMessage, p["in_reply_to_email_id"])
                if original is None or original.user_id != user.id:
                    raise ActionRejected("Original email not found")
            client = _google(db, user.id)
            if client:
                msg_id = client.send_message(p["to"], p["subject"], p["body"],
                                             thread_id=original.thread_id if original else None,
                                             in_reply_to=original.message_id_header if original else None)
                action.result = {"sent": True, "provider_message_id": msg_id}
            else:
                action.result = {"sent": False, "simulated": True,
                                 "note": "No mail provider connected (demo mode); nothing was sent."}
            if original:
                original.needs_reply = False

        action.status = "executed"
        action.executed_at = utcnow()
        action.error = None
        audit.record(db, f"agent.{action.kind}", user.id, None, action_id=action.id, auto=auto)
    except (ActionRejected, google.ProviderError) as exc:
        action.status = "failed"
        action.error = str(exc)[:500]
        audit.record(db, "agent.action_failed", user.id, None, action_id=action.id, kind=action.kind)
    return action
