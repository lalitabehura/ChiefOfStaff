"""Transactional email for account flows (password reset). Logs instead of sending in development."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("app.mailer")


def send_system_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        if s.is_production:
            log.error("SMTP not configured; cannot send '%s'", subject)
        else:
            log.warning("DEV MAIL to=%s subject=%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password or "")
        smtp.send_message(msg)
