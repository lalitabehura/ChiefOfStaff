from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_preferences
from app.models import CalendarEvent, Preferences, User
from app.schemas import ActionOut, EventIn, EventOut, SlotOut
from app.services import actions, audit
from app.services.scheduler import events_between, free_slots, plan_day

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/events", response_model=list[EventOut])
def list_events(day: date | None = None, days: int = Query(default=1, ge=1, le=31),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = ZoneInfo(user.timezone)
    start_day = day or datetime.now(tz).date()
    start = datetime.combine(start_day, time.min, tzinfo=tz)
    return events_between(db, user.id, start, start + timedelta(days=days))


@router.post("/events", response_model=ActionOut, status_code=201)
def create_event(body: EventIn, user: User = Depends(get_current_user),
                 prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    """User-created events execute immediately (they are the user's own explicit action),
    but still flow through the action pipeline for validation, provider sync and auditing."""
    tz = ZoneInfo(user.timezone)
    start = body.start if body.start.tzinfo else body.start.replace(tzinfo=tz)
    end = body.end if body.end.tzinfo else body.end.replace(tzinfo=tz)
    action = actions.propose(db, user, prefs, "create_event", {
        "title": body.title, "start": start.isoformat(), "end": end.isoformat(),
        "attendees": [str(a) for a in body.attendees], "description": body.description,
    }, rationale="Created by you", confidence=1.0, source="user", force_approval=True)
    actions.execute(db, user, action)
    db.commit()
    if action.status == "failed":
        raise HTTPException(status_code=502, detail=action.error)
    return action


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, event_id)
    if ev is None or ev.user_id != user.id:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.source == "google":
        raise HTTPException(status_code=400, detail="Delete Google events in Google Calendar.")
    db.delete(ev)
    audit.record(db, "calendar.event_deleted", user.id, request)
    db.commit()


@router.get("/free-slots", response_model=list[SlotOut])
def get_free_slots(day: date | None = None, min_minutes: int = Query(default=30, ge=5, le=480),
                   user: User = Depends(get_current_user), prefs: Preferences = Depends(get_preferences),
                   db: Session = Depends(get_db)):
    d = day or datetime.now(ZoneInfo(user.timezone)).date()
    return [SlotOut(start=s, end=e) for s, e in free_slots(db, user, prefs, d, min_minutes)]


@router.post("/plan-day", response_model=list[ActionOut])
def plan_my_day(day: date | None = None, user: User = Depends(get_current_user),
                prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    d = day or datetime.now(ZoneInfo(user.timezone)).date()
    created = []
    for task, (s, e) in plan_day(db, user, prefs, d):
        created.append(actions.propose(db, user, prefs, "create_event", {
            "title": f"Focus: {task.title}"[:300], "start": s.isoformat(), "end": e.isoformat(),
            "task_id": task.id, "is_focus_block": True,
        }, rationale=f"Priority {task.priority_score}: {task.priority_reason}", confidence=0.75, source="planner"))
    db.commit()
    return created
