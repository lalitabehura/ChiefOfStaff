"""User-defined automation rules evaluated on new email."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AutomationRule, EmailMessage, Preferences, User
from app.services import actions
from app.services.triage import draft_reply, sender_address


def matches(rule: AutomationRule, email: EmailMessage) -> bool:
    c = rule.conditions or {}
    checks = []
    if c.get("from_contains"):
        checks.append(c["from_contains"].lower() in email.sender.lower())
    if c.get("subject_contains"):
        checks.append(c["subject_contains"].lower() in email.subject.lower())
    if c.get("body_contains"):
        checks.append(c["body_contains"].lower() in (email.body or "").lower())
    if c.get("category"):
        checks.append(email.category == c["category"])
    return bool(checks) and all(checks)


def apply_rules(db: Session, user: User, prefs: Preferences, email: EmailMessage) -> int:
    rules = db.scalars(select(AutomationRule).where(
        AutomationRule.user_id == user.id, AutomationRule.enabled.is_(True),
        AutomationRule.trigger == "email_received")).all()
    fired = 0
    for rule in rules:
        if not matches(rule, email):
            continue
        a = rule.action or {}
        kind = a.get("type")
        if kind == "set_category":
            email.category = a["category"]
            email.triage_reason = f"Rule: {rule.name}"[:300]
        elif kind == "mark_read":
            email.is_read = True
        elif kind == "create_task":
            # A rule the user explicitly set to 'auto' runs internal actions immediately;
            # 'suggest' rules queue them for approval.
            act = actions.propose(db, user, prefs, "create_task",
                                  {"title": f"{email.subject or 'Email'} ({sender_address(email)})"[:200],
                                   "importance": a.get("importance", 3), "source_email_id": email.id},
                                  rationale=f"Rule '{rule.name}' matched", confidence=0.9, source="rule",
                                  force_approval=True)
            if rule.autonomy == "auto":
                actions.execute(db, user, act)
        elif kind == "draft_reply":
            draft = draft_reply(db, user, prefs, email, a.get("instructions", ""))
            to = sender_address(email)
            if to:
                actions.propose(db, user, prefs, "send_email",
                                {"to": [to], "subject": draft.subject, "body": draft.body,
                                 "in_reply_to_email_id": email.id},
                                rationale=f"Rule '{rule.name}' drafted a reply", confidence=0.7,
                                source="rule", force_approval=True)
        rule.times_fired += 1
        fired += 1
    return fired
