"""Background worker (arq + Redis): periodic sync, re-prioritisation and housekeeping.

Run: arq app.worker.WorkerSettings
"""
import asyncio
import logging
from datetime import timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.security import utcnow
from app.db import SessionLocal
from app.models import (
    Integration,
    OAuthState,
    PasswordResetToken,
    Preferences,
    RefreshToken,
    User,
)
from app.services.prioritizer import reprioritize
from app.services.sync import sync_user

log = logging.getLogger("app.worker")


def _sync_all() -> int:
    count = 0
    with SessionLocal() as db:
        user_ids = db.scalars(select(Integration.user_id).where(Integration.status == "active").distinct()).all()
    for uid in user_ids:
        with SessionLocal() as db:  # one transaction per user: one failure doesn't block others
            try:
                user = db.get(User, uid)
                if user and user.is_active:
                    sync_user(db, user)
                    db.commit()
                    count += 1
            except Exception:
                db.rollback()
                log.exception("sync failed for user %s", uid)
    return count


def _reprioritize_all() -> None:
    with SessionLocal() as db:
        for prefs in db.scalars(select(Preferences)).all():
            reprioritize(db, prefs.user_id, prefs)
        db.commit()


def _housekeeping() -> None:
    now = utcnow()
    with SessionLocal() as db:
        db.execute(delete(OAuthState).where(OAuthState.expires_at < now))
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now - timedelta(days=1)))
        db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1)))
        db.commit()


async def sync_all(ctx) -> int:
    return await asyncio.to_thread(_sync_all)


async def reprioritize_all(ctx) -> None:
    await asyncio.to_thread(_reprioritize_all)


async def housekeeping(ctx) -> None:
    await asyncio.to_thread(_housekeeping)


class WorkerSettings:
    functions = [sync_all, reprioritize_all, housekeeping]
    cron_jobs = [
        cron(sync_all, minute={0, 10, 20, 30, 40, 50}),
        cron(reprioritize_all, minute={5, 35}),
        cron(housekeeping, hour={3}, minute={15}),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379/0")
    max_jobs = 4
    job_timeout = 300
