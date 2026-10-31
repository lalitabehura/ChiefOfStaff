"""Habit learning. Small, transparent online updates the user can inspect (Preferences.learned)
and reset at any time. No raw content is used for learning - only structured signals."""
from collections import Counter

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.security import utcnow
from app.models import FeedbackEvent, Preferences, Task
from app.services.prioritizer import (
    DEFAULT_WEIGHTS,
    FEATURES,
    get_weights,
    task_features,
)

LEARNING_RATE = 0.05


def _save(prefs: Preferences, learned: dict) -> None:
    prefs.learned = learned
    flag_modified(prefs, "learned")


def apply_priority_feedback(db: Session, prefs: Preferences, task: Task, signal: float) -> dict:
    """signal=+1 'should be higher', -1 'should be lower'. Nudges feature weights and tag boosts."""
    learned = dict(prefs.learned or {})
    weights = get_weights(prefs)
    feats = task_features(task, utcnow())
    for k in FEATURES:
        weights[k] = max(0.02, weights[k] + LEARNING_RATE * signal * (feats[k] - 0.5))
    total = sum(weights.values())
    learned["priority_weights"] = {k: round(v / total, 4) for k, v in weights.items()}

    boosts = dict(learned.get("tag_boosts", {}))
    for tag in task.tags or []:
        key = tag.lower()
        boosts[key] = round(max(-0.3, min(0.3, boosts.get(key, 0.0) + LEARNING_RATE * signal)), 4)
    learned["tag_boosts"] = boosts
    _save(prefs, learned)
    db.add(FeedbackEvent(user_id=prefs.user_id, kind="priority", target_id=task.id, signal=signal))
    return learned


def record_action_decision(db: Session, prefs: Preferences, kind: str, approved: bool, edited: bool) -> None:
    """Track approval rates per action type so the agent can suggest more autonomy where trusted."""
    learned = dict(prefs.learned or {})
    stats = dict(learned.get("approval_stats", {}))
    s = dict(stats.get(kind, {"approved": 0, "rejected": 0, "edited": 0}))
    s["approved" if approved else "rejected"] += 1
    if edited:
        s["edited"] += 1
    stats[kind] = s
    learned["approval_stats"] = stats
    _save(prefs, learned)
    db.add(FeedbackEvent(user_id=prefs.user_id, kind=f"action:{kind}", signal=1.0 if approved else -1.0,
                         meta={"edited": edited}))


def record_scheduled_hour(db: Session, prefs: Preferences, local_hour: int) -> None:
    """Learn which hours the user accepts for focus work."""
    learned = dict(prefs.learned or {})
    hist = Counter({int(k): v for k, v in learned.get("focus_hours", {}).items()})
    hist[local_hour] += 1
    learned["focus_hours"] = {str(k): v for k, v in hist.items()}
    _save(prefs, learned)


def preferred_hours(prefs: Preferences) -> list[int]:
    hist = (prefs.learned or {}).get("focus_hours", {})
    return [int(h) for h, _ in sorted(hist.items(), key=lambda kv: kv[1], reverse=True)][:3]


def autonomy_suggestions(prefs: Preferences) -> list[str]:
    tips = []
    for kind, s in (prefs.learned or {}).get("approval_stats", {}).items():
        total = s["approved"] + s["rejected"]
        if kind != "send_email" and total >= 10 and s["approved"] / total >= 0.9 and s["edited"] <= 1:
            tips.append(f"You approve nearly all '{kind}' suggestions. Consider the 'balanced' or "
                        "'auto' autonomy level in Settings.")
    return tips


def reset_learning(prefs: Preferences) -> None:
    _save(prefs, {"priority_weights": dict(DEFAULT_WEIGHTS)})
