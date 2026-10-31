"""Conversational agent: turns natural-language requests into replies + proposed actions."""
import re
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import AgentAction, AgentMessage, CalendarEvent, Preferences, Task, User
from app.services import actions
from app.services.ai import get_ai, wrap_untrusted
from app.services.brief import build_brief
from app.services.prioritizer import reprioritize
from app.services.scheduler import find_slot, plan_day


class PlannedAction(BaseModel):
    kind: Literal["create_task", "complete_task", "create_event", "send_email"]
    payload: dict
    rationale: str = Field(default="", max_length=500)


class AgentPlan(BaseModel):
    reply: str = Field(max_length=4000)
    actions: list[PlannedAction] = Field(default_factory=list, max_length=5)


AGENT_TASK = """Help the user manage their work. Use the workspace context to answer questions and \
propose at most 5 actions. Action payload formats:
- create_task: {title, description?, due_at? (ISO 8601 with offset), importance 1-5, estimate_minutes, tags[]}
- complete_task: {task_id, title}   (task_id MUST come from the context list)
- create_event: {title, start, end (ISO 8601 with offset), attendees[], description?, task_id?, is_focus_block}
- send_email: {to[], subject, body}  (only when the user explicitly asks to email someone)
Only use email addresses the USER typed in their message or that appear as a sender the user refers to. \
Times must respect the user's timezone and working hours. Keep the reply short and concrete."""


def _context(db: Session, user: User, prefs: Preferences) -> str:
    tz = ZoneInfo(user.timezone)
    now = utcnow()
    tasks = reprioritize(db, user.id, prefs)[:15]
    events = db.scalars(select(CalendarEvent).where(
        CalendarEvent.user_id == user.id, CalendarEvent.start >= now - timedelta(hours=2),
        CalendarEvent.start < now + timedelta(days=3)).order_by(CalendarEvent.start).limit(20)).all()
    task_lines = "\n".join(
        f"- id={t.id} | {t.title} | score={t.priority_score} | due={t.due_at.astimezone(tz).isoformat() if t.due_at else 'none'}"
        f" | est={t.estimate_minutes}m" for t in tasks)
    event_lines = "\n".join(
        f"- {e.start.astimezone(tz).isoformat()} -> {e.end.astimezone(tz).isoformat()} | {e.title}" for e in events)
    return wrap_untrusted("workspace", f"OPEN TASKS (by priority):\n{task_lines or '(none)'}\n\n"
                                       f"UPCOMING EVENTS:\n{event_lines or '(none)'}", limit=12000)


def _parse_due(text: str, tz: ZoneInfo) -> datetime | None:
    today = utcnow().astimezone(tz).date()
    if re.search(r"\btoday\b", text, re.I):
        return datetime.combine(today, time(17, 0), tzinfo=tz)
    if re.search(r"\btomorrow\b", text, re.I):
        return datetime.combine(today + timedelta(days=1), time(17, 0), tzinfo=tz)
    m = re.search(r"\bin (\d{1,2}) days?\b", text, re.I)
    if m:
        return datetime.combine(today + timedelta(days=int(m.group(1))), time(17, 0), tzinfo=tz)
    return None


def _fallback(db: Session, user: User, prefs: Preferences, message: str) -> AgentPlan:
    """Deterministic intent parser used when no AI key is configured or the model fails."""
    tz = ZoneInfo(user.timezone)
    text = message.strip()
    low = text.lower()

    m = re.match(r"^(?:add|create|new)(?: a)? task[:\s]+(.+)$|^remind me to (.+)$", text, re.I)
    if m:
        raw = (m.group(1) or m.group(2)).strip()
        due = _parse_due(raw, tz)
        title = re.sub(r"\b(today|tomorrow|in \d{1,2} days?)\b", "", raw, flags=re.I).strip(" ,.") or raw
        imp = 5 if re.search(r"\b(urgent|important|asap)\b", low) else 3
        return AgentPlan(reply=f"I'll add \"{title}\" to your tasks.", actions=[PlannedAction(
            kind="create_task", payload={"title": title[:200], "importance": imp,
                                         "due_at": due.isoformat() if due else None},
            rationale="You asked me to add a task")])

    if re.search(r"\b(plan|schedule|organi[sz]e) (my )?(day|today)\b", low):
        plan = plan_day(db, user, prefs, utcnow().astimezone(tz).date())
        if not plan:
            return AgentPlan(reply="I couldn't find free time today for your open tasks.")
        acts = [PlannedAction(kind="create_event", payload={
            "title": f"Focus: {t.title}"[:300], "start": s.isoformat(), "end": e.isoformat(),
            "task_id": t.id, "is_focus_block": True}, rationale=f"Priority {t.priority_score}: {t.priority_reason}")
            for t, (s, e) in plan]
        lines = "\n".join(f"• {s.astimezone(tz):%H:%M}-{e.astimezone(tz):%H:%M} {t.title}" for t, (s, e) in plan)
        return AgentPlan(reply=f"Here's a plan for today:\n{lines}", actions=acts)

    m = re.match(r"^(?:schedule|block time for|find time for)\s+(.+)$", text, re.I)
    if m:
        target = m.group(1).strip().lower()
        task = next((t for t in reprioritize(db, user.id, prefs) if target in t.title.lower()), None)
        if task:
            slot = find_slot(db, user, prefs, task.estimate_minutes)
            if slot:
                s, e = slot
                return AgentPlan(reply=f"Found {s.astimezone(tz):%a %H:%M} for \"{task.title}\".", actions=[
                    PlannedAction(kind="create_event", payload={
                        "title": f"Focus: {task.title}", "start": s.isoformat(), "end": e.isoformat(),
                        "task_id": task.id, "is_focus_block": True}, rationale="Earliest suitable free slot")])
            return AgentPlan(reply="No free slot in the next week fits that task.")

    m = re.match(r"^(?:complete|done|finish(?:ed)?|mark done)\s+(?:task\s+)?(.+)$", text, re.I)
    if m:
        target = m.group(1).strip().lower()
        task = db.scalars(select(Task).where(Task.user_id == user.id, Task.status != "done")).all()
        match = next((t for t in task if target in t.title.lower()), None)
        if match:
            return AgentPlan(reply=f"Marking \"{match.title}\" as done.", actions=[PlannedAction(
                kind="complete_task", payload={"task_id": match.id, "title": match.title},
                rationale="You said it's finished")])
        return AgentPlan(reply="I couldn't find an open task with that name.")

    if re.search(r"\b(priorit|what should i (do|work on)|focus)\b", low):
        top = reprioritize(db, user.id, prefs)[:3]
        if not top:
            return AgentPlan(reply="You have no open tasks. 🎉")
        return AgentPlan(reply="Your top priorities:\n" + "\n".join(
            f"{i + 1}. {t.title} - {t.priority_reason}" for i, t in enumerate(top)))

    if re.search(r"\b(brief|agenda|my day|today|schedule)\b", low):
        return AgentPlan(reply=build_brief(db, user, prefs)["summary"])

    return AgentPlan(reply=(
        "I can help with things like:\n• \"Add task send invoice tomorrow\"\n• \"Plan my day\"\n"
        "• \"Schedule board report\"\n• \"What should I work on?\"\n• \"Done vendor pricing\"\n"
        "Connect an Anthropic API key for free-form requests."))


def chat(db: Session, user: User, prefs: Preferences, message: str) -> tuple[str, list[AgentAction]]:
    history = db.scalars(select(AgentMessage).where(AgentMessage.user_id == user.id)
                         .order_by(AgentMessage.created_at.desc()).limit(10)).all()[::-1]
    db.add(AgentMessage(user_id=user.id, role="user", content=message))
    tz = ZoneInfo(user.timezone)
    convo = "\n".join(f"{m.role.upper()}: {m.content[:1500]}" for m in history)
    content = (f"Now: {utcnow().astimezone(tz).isoformat()} ({user.timezone})\n"
               f"Working hours: {prefs.work_start}-{prefs.work_end}, days {prefs.work_days} (0=Mon)\n\n"
               f"{_context(db, user, prefs)}\n\nRECENT CONVERSATION:\n{convo or '(none)'}\n\n"
               f"USER REQUEST (trusted): {message}")
    plan = get_ai().complete_json(user.id, AGENT_TASK, content, AgentPlan, max_tokens=1500)
    if plan is None:
        plan = _fallback(db, user, prefs, message)

    created: list[AgentAction] = []
    notes: list[str] = []
    for pa in plan.actions:
        if pa.kind == "send_email":
            # Recipients must be typed by the user - blocks injected-content exfiltration.
            to = [str(a).lower() for a in pa.payload.get("to", [])]
            if not to or any(addr not in message.lower() for addr in to):
                notes.append("I skipped an email draft because its recipient wasn't in your message.")
                continue
        try:
            created.append(actions.propose(db, user, prefs, pa.kind, pa.payload, pa.rationale,
                                           confidence=0.7, source="agent"))
        except actions.ActionRejected as exc:
            notes.append(f"Skipped an invalid suggestion ({exc}).")
    reply = plan.reply + ("\n\n" + "\n".join(notes) if notes else "")
    pending = sum(1 for a in created if a.status == "pending")
    if pending:
        reply += f"\n\n{pending} action(s) are waiting for your approval."
    db.add(AgentMessage(user_id=user.id, role="assistant", content=reply))
    return reply, created
