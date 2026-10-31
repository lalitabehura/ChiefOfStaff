"""Explainable task prioritisation. Weights are personalised by services/learning.py."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import Preferences, Task

DEFAULT_WEIGHTS = {"urgency": 0.45, "importance": 0.35, "quick_win": 0.10, "age": 0.10}
FEATURES = tuple(DEFAULT_WEIGHTS)


def task_features(task: Task, now: datetime) -> dict[str, float]:
    if task.due_at:
        hours = (task.due_at - now).total_seconds() / 3600
        urgency = 1.0 if hours <= 0 else 1.0 / (1.0 + hours / 24.0)
    else:
        urgency = 0.1
    importance = (task.importance - 1) / 4
    est = task.estimate_minutes or 30
    quick_win = 1.0 if est <= 15 else 0.6 if est <= 30 else 0.3 if est <= 60 else 0.1
    age = min((now - task.created_at).total_seconds() / 86400 / 14, 1.0)
    return {"urgency": urgency, "importance": importance, "quick_win": quick_win, "age": age}


def get_weights(prefs: Preferences | None) -> dict[str, float]:
    learned = (prefs.learned or {}) if prefs else {}
    weights = dict(DEFAULT_WEIGHTS)
    weights.update({k: v for k, v in learned.get("priority_weights", {}).items() if k in weights})
    return weights


_LABELS = {
    "urgency": "due soon",
    "importance": "high importance",
    "quick_win": "quick win",
    "age": "waiting a while",
}


def score_task(task: Task, prefs: Preferences | None, now: datetime | None = None) -> tuple[float, str]:
    now = now or utcnow()
    feats = task_features(task, now)
    weights = get_weights(prefs)
    contributions = {k: weights[k] * feats[k] for k in FEATURES}
    tag_boosts = ((prefs.learned or {}).get("tag_boosts", {}) if prefs else {})
    tag_bonus = sum(tag_boosts.get(t.lower(), 0.0) for t in (task.tags or []))
    score = sum(contributions.values()) + tag_bonus

    reasons = []
    if task.due_at and task.due_at <= now:
        reasons.append("overdue")
    top = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:2]
    reasons += [_LABELS[k] for k, v in top if v > 0.05 and not (k == "urgency" and "overdue" in reasons)]
    if tag_bonus > 0.02:
        reasons.append("you usually prioritise these tags")
    elif tag_bonus < -0.02:
        reasons.append("you usually deprioritise these tags")
    return round(score * 100, 1), ", ".join(reasons) or "baseline"


def reprioritize(db: Session, user_id: str, prefs: Preferences | None) -> list[Task]:
    tasks = db.scalars(select(Task).where(Task.user_id == user_id, Task.status != "done")).all()
    now = utcnow()
    for t in tasks:
        t.priority_score, t.priority_reason = score_task(t, prefs, now)
    db.flush()
    return sorted(tasks, key=lambda t: t.priority_score, reverse=True)
