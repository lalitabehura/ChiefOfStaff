from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.db import get_db
from app.deps import get_current_user, get_preferences
from app.models import Preferences, Task, User
from app.schemas import ActionOut, TaskFeedbackIn, TaskIn, TaskOut, TaskUpdate
from app.services import actions, audit
from app.services.learning import apply_priority_feedback
from app.services.prioritizer import reprioritize, score_task
from app.services.scheduler import find_slot

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_owned(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")  # 404, not 403: no existence leak
    return task


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(t.strip().lower()[:32] for t in tags if t.strip()))[:10]


@router.get("", response_model=list[TaskOut])
def list_tasks(status: str | None = Query(default=None, pattern="^(todo|in_progress|done|open)$"),
               q: str | None = Query(default=None, max_length=100),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Task).where(Task.user_id == user.id)
    if status == "open":
        stmt = stmt.where(Task.status != "done")
    elif status:
        stmt = stmt.where(Task.status == status)
    if q:
        stmt = stmt.where(Task.title.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    return db.scalars(stmt.order_by(Task.priority_score.desc(), Task.created_at.desc()).limit(500)).all()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskIn, user: User = Depends(get_current_user),
                prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    task = Task(user_id=user.id, **body.model_dump(exclude={"tags"}), tags=_clean_tags(body.tags))
    db.add(task)
    db.flush()
    task.priority_score, task.priority_reason = score_task(task, prefs)
    db.commit()
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdate, user: User = Depends(get_current_user),
                prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    task = _get_owned(db, user, task_id)
    data = body.model_dump(exclude_unset=True)
    if "tags" in data and data["tags"] is not None:
        data["tags"] = _clean_tags(data["tags"])
    for k, v in data.items():
        setattr(task, k, v)
    if data.get("status") == "done" and not task.completed_at:
        task.completed_at = utcnow()
    elif data.get("status") and data["status"] != "done":
        task.completed_at = None
    task.priority_score, task.priority_reason = score_task(task, prefs)
    db.commit()
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _get_owned(db, user, task_id)
    db.delete(task)
    audit.record(db, "task.deleted", user.id, request, task_id=task_id)
    db.commit()


@router.post("/prioritize", response_model=list[TaskOut])
def prioritize(user: User = Depends(get_current_user), prefs: Preferences = Depends(get_preferences),
               db: Session = Depends(get_db)):
    tasks = reprioritize(db, user.id, prefs)
    db.commit()
    return tasks


@router.post("/{task_id}/feedback", response_model=TaskOut)
def priority_feedback(task_id: str, body: TaskFeedbackIn, user: User = Depends(get_current_user),
                      prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    """'This should be higher/lower' - teaches the prioritiser the user's habits."""
    task = _get_owned(db, user, task_id)
    apply_priority_feedback(db, prefs, task, 1.0 if body.signal == "more_important" else -1.0)
    task.importance = max(1, min(5, task.importance + (1 if body.signal == "more_important" else -1)))
    reprioritize(db, user.id, prefs)
    db.commit()
    return task


@router.post("/{task_id}/schedule", response_model=ActionOut)
def schedule_task(task_id: str, user: User = Depends(get_current_user),
                  prefs: Preferences = Depends(get_preferences), db: Session = Depends(get_db)):
    task = _get_owned(db, user, task_id)
    slot = find_slot(db, user, prefs, task.estimate_minutes)
    if slot is None:
        raise HTTPException(status_code=409, detail="No free slot in the next 7 days.")
    start, end = slot
    action = actions.propose(db, user, prefs, "create_event", {
        "title": f"Focus: {task.title}"[:300], "start": start.isoformat(), "end": end.isoformat(),
        "task_id": task.id, "is_focus_block": True,
    }, rationale="Earliest free slot matching your working hours and habits", confidence=0.8, source="planner")
    db.commit()
    return action
