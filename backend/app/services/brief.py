"""Daily brief: what matters today, in one view."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import AgentAction, CalendarEvent, EmailMessage, Preferences, User
from app.services.learning import autonomy_suggestions
from app.services.prioritizer import reprioritize
from app.services.scheduler import free_slots


def build_brief(db: Session, user: User, prefs: Preferences) -> dict:
    tz = ZoneInfo(user.timezone)
    now = utcnow()
    today = now.astimezone(tz).date()
    day_start = datetime.combine(today, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    tasks = reprioritize(db, user.id, prefs)
    overdue = [t for t in tasks if t.due_at and t.due_at < now]
    events = db.scalars(select(CalendarEvent).where(
        CalendarEvent.user_id == user.id, CalendarEvent.start < day_end, CalendarEvent.end > day_start,
    ).order_by(CalendarEvent.start)).all()
    urgent = db.scalars(select(EmailMessage).where(
        EmailMessage.user_id == user.id, EmailMessage.category.in_(["urgent", "action"]),
        EmailMessage.needs_reply.is_(True),
    ).order_by(EmailMessage.received_at.desc()).limit(5)).all()
    pending = db.scalar(select(func.count()).select_from(AgentAction).where(
        AgentAction.user_id == user.id, AgentAction.status == "pending")) or 0
    slots = free_slots(db, user, prefs, today)
    free_minutes = int(sum((e - s).total_seconds() for s, e in slots) // 60)
    meeting_minutes = int(sum((min(e.end, day_end) - max(e.start, day_start)).total_seconds() for e in events) // 60)

    hour = now.astimezone(tz).hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    name = user.full_name.split(" ")[0] if user.full_name else ""
    parts = [f"{greeting}{', ' + name if name else ''}."]
    parts.append(f"You have {len(events)} event(s) today ({meeting_minutes} min) and {free_minutes} min of free time.")
    if tasks:
        parts.append(f"Top priority: \"{tasks[0].title}\" ({tasks[0].priority_reason}).")
    if overdue:
        parts.append(f"{len(overdue)} task(s) are overdue.")
    if urgent:
        parts.append(f"{len(urgent)} email(s) need a reply.")
    if pending:
        parts.append(f"{pending} suggestion(s) are waiting for your approval.")

    return {
        "summary": " ".join(parts),
        "date": today.isoformat(),
        "events": events,
        "top_tasks": tasks[:5],
        "overdue_count": len(overdue),
        "emails_needing_reply": urgent,
        "pending_approvals": pending,
        "free_minutes": free_minutes,
        "meeting_minutes": meeting_minutes,
        "tips": autonomy_suggestions(prefs),
    }
