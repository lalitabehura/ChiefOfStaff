"""Calendar intelligence: free-slot search respecting working hours, buffers and learned habits."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import CalendarEvent, Preferences, Task, User
from app.services.learning import preferred_hours

Slot = tuple[datetime, datetime]


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def working_window(day: date, prefs: Preferences, tz: ZoneInfo) -> Slot | None:
    if day.weekday() not in (prefs.work_days or [0, 1, 2, 3, 4]):
        return None
    start = datetime.combine(day, _hm(prefs.work_start), tzinfo=tz)
    end = datetime.combine(day, _hm(prefs.work_end), tzinfo=tz)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


def events_between(db: Session, user_id: str, start: datetime, end: datetime) -> list[CalendarEvent]:
    return list(db.scalars(select(CalendarEvent).where(
        CalendarEvent.user_id == user_id, CalendarEvent.end > start, CalendarEvent.start < end,
    ).order_by(CalendarEvent.start)).all())


def free_slots(db: Session, user: User, prefs: Preferences, day: date, min_minutes: int = 15) -> list[Slot]:
    tz = ZoneInfo(user.timezone)
    window = working_window(day, prefs, tz)
    if window is None:
        return []
    w_start, w_end = window
    now = utcnow()
    if w_end <= now:
        return []
    w_start = max(w_start, now.replace(second=0, microsecond=0))
    buffer = timedelta(minutes=prefs.meeting_buffer_minutes)
    busy = [(e.start - buffer, e.end + buffer) for e in events_between(db, user.id, w_start, w_end)]
    busy.sort()

    slots: list[Slot] = []
    cursor = w_start
    for b_start, b_end in busy:
        if b_start > cursor:
            slots.append((cursor, min(b_start, w_end)))
        cursor = max(cursor, b_end)
        if cursor >= w_end:
            break
    if cursor < w_end:
        slots.append((cursor, w_end))
    need = timedelta(minutes=min_minutes)
    return [(s, e) for s, e in slots if e - s >= need]


def find_slot(db: Session, user: User, prefs: Preferences, minutes: int, horizon_days: int = 7,
              not_before: datetime | None = None) -> Slot | None:
    """Earliest slot of `minutes`, preferring hours the user habitually accepts."""
    tz = ZoneInfo(user.timezone)
    today = utcnow().astimezone(tz).date()
    prefer = preferred_hours(prefs)
    duration = timedelta(minutes=minutes)
    for offset in range(horizon_days):
        day = today + timedelta(days=offset)
        candidates: list[datetime] = []
        for s, e in free_slots(db, user, prefs, day, minutes):
            if not_before and e <= not_before:
                continue
            start = max(s, not_before) if not_before else s
            # round up to next 15 minutes for tidy calendars
            start = start + timedelta(minutes=(-start.minute) % 15)
            start = start.replace(second=0, microsecond=0)
            while start + duration <= e:
                candidates.append(start)
                start += timedelta(minutes=30)
        if candidates:
            if prefer:
                preferred = [c for c in candidates if c.astimezone(tz).hour in prefer]
                if preferred:
                    return preferred[0], preferred[0] + duration
            return candidates[0], candidates[0] + duration
    return None


def plan_day(db: Session, user: User, prefs: Preferences, day: date, max_tasks: int = 5) -> list[tuple[Task, Slot]]:
    """Greedy: place highest-priority unscheduled tasks into today's free slots."""
    tasks = db.scalars(select(Task).where(
        Task.user_id == user.id, Task.status != "done", Task.scheduled_start.is_(None),
    ).order_by(Task.priority_score.desc())).all()
    slots = [list(s) for s in free_slots(db, user, prefs, day)]
    plan: list[tuple[Task, Slot]] = []
    for task in tasks:
        if len(plan) >= max_tasks:
            break
        need = timedelta(minutes=task.estimate_minutes)
        for slot in slots:
            start = slot[0] + timedelta(minutes=(-slot[0].minute) % 15)
            start = start.replace(second=0, microsecond=0)
            if slot[1] - start >= need:
                plan.append((task, (start, start + need)))
                slot[0] = start + need + timedelta(minutes=prefs.meeting_buffer_minutes)
                break
    return plan
