"""Pulls mail and calendar from connected providers, then triages and runs rules on new mail."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.models import CalendarEvent, EmailMessage, Integration, Preferences, User
from app.services import audit
from app.services.providers import google
from app.services.rules import apply_rules
from app.services.triage import triage_email

log = logging.getLogger("app.sync")


def process_new_emails(db: Session, user: User, prefs: Preferences, emails: list[EmailMessage]) -> None:
    for email in emails:
        triage_email(db, user, email)
        apply_rules(db, user, prefs, email)


def sync_google(db: Session, user: User, integ: Integration) -> dict:
    client = google.GoogleClient(db, integ)
    prefs = db.get(Preferences, user.id)
    new_emails = []
    for m in client.list_recent_messages():
        exists = db.scalar(select(EmailMessage.id).where(
            EmailMessage.user_id == user.id, EmailMessage.external_id == m["external_id"]))
        if exists:
            continue
        email = EmailMessage(user_id=user.id, external_id=m["external_id"], thread_id=m["thread_id"],
                             message_id_header=m["message_id_header"], sender=m["sender"], subject=m["subject"],
                             snippet=m["snippet"], body=m["body"], received_at=m["received_at"], is_read=m["is_read"])
        db.add(email)
        new_emails.append(email)
    db.flush()
    process_new_emails(db, user, prefs, new_emails)

    now = utcnow()
    count_events = 0
    for e in client.list_events(now - timedelta(days=1), now + timedelta(days=14)):
        ev = db.scalar(select(CalendarEvent).where(
            CalendarEvent.user_id == user.id, CalendarEvent.external_id == e["external_id"]))
        if ev is None:
            ev = CalendarEvent(user_id=user.id, external_id=e["external_id"], source="google")
            db.add(ev)
        ev.title, ev.description, ev.location = e["title"], e["description"], e["location"]
        ev.start, ev.end, ev.attendees = e["start"], e["end"], e["attendees"]
        count_events += 1
    integ.last_synced_at = now
    return {"new_emails": len(new_emails), "events": count_events}


def sync_user(db: Session, user: User) -> dict:
    result = {"new_emails": 0, "events": 0, "errors": []}
    integrations = db.scalars(select(Integration).where(Integration.user_id == user.id)).all()
    for integ in integrations:
        if integ.provider == "google" and integ.status == "active":
            try:
                r = sync_google(db, user, integ)
                result["new_emails"] += r["new_emails"]
                result["events"] += r["events"]
            except google.ProviderError as exc:
                result["errors"].append(str(exc))
                log.warning("google sync failed for user %s: %s", user.id, exc)
        elif integ.provider == "demo":
            integ.last_synced_at = utcnow()
    # Also triage anything that arrived without triage (e.g. demo data)
    prefs = db.get(Preferences, user.id)
    pending = db.scalars(select(EmailMessage).where(
        EmailMessage.user_id == user.id, EmailMessage.triaged.is_(False))).all()
    process_new_emails(db, user, prefs, list(pending))
    audit.record(db, "sync.completed", user.id, None, new_emails=result["new_emails"])
    return result
