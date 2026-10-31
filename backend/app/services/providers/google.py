"""Google Gmail + Calendar via OAuth 2.0 (authorization code + PKCE). Tokens are encrypted at rest."""
import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage as MimeMessage
from email.utils import getaddresses, parsedate_to_datetime
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utcnow
from app.models import Integration

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary"

# Least privilege: read/label mail, send mail, manage events. No Drive, no contacts, no full mail delete.
SCOPES = [
    "openid", "email",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]
_TIMEOUT = httpx.Timeout(15.0)


class ProviderError(Exception):
    pass


def is_configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(state: str, code_challenge: str) -> str:
    s = get_settings()
    return AUTH_URL + "?" + urlencode({
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def exchange_code(code: str, verifier: str) -> dict:
    s = get_settings()
    r = httpx.post(TOKEN_URL, data={
        "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
        "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    }, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise ProviderError("Token exchange failed")
    tokens = r.json()
    info = httpx.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}, timeout=_TIMEOUT)
    tokens["email"] = info.json().get("email", "") if info.status_code == 200 else ""
    return tokens


def revoke(token: str) -> None:
    try:
        httpx.post(REVOKE_URL, data={"token": token}, timeout=_TIMEOUT)
    except httpx.HTTPError:
        pass


def _header_safe(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


class GoogleClient:
    def __init__(self, db: Session, integration: Integration):
        self.db = db
        self.integ = integration

    # ------------------------------------------------------------------ token handling
    def _token(self) -> str:
        integ = self.integ
        if integ.expires_at and integ.expires_at > utcnow() + timedelta(seconds=60):
            return integ.access_token or ""
        if not integ.refresh_token:
            integ.status = "reauth_required"
            raise ProviderError("Google access expired; reconnect the integration")
        s = get_settings()
        r = httpx.post(TOKEN_URL, data={
            "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "refresh_token": integ.refresh_token, "grant_type": "refresh_token",
        }, timeout=_TIMEOUT)
        if r.status_code != 200:
            integ.status = "reauth_required"
            raise ProviderError("Could not refresh Google token; reconnect the integration")
        data = r.json()
        integ.access_token = data["access_token"]
        integ.expires_at = utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)))
        integ.status = "active"
        self.db.flush()
        return integ.access_token

    def _request(self, method: str, url: str, **kwargs) -> dict:
        r = httpx.request(method, url, headers={"Authorization": f"Bearer {self._token()}"},
                          timeout=_TIMEOUT, **kwargs)
        if r.status_code >= 400:
            raise ProviderError(f"Google API error {r.status_code}")
        return r.json() if r.content else {}

    # ------------------------------------------------------------------ Gmail
    def list_recent_messages(self, max_results: int = 25, days: int = 3) -> list[dict]:
        listing = self._request("GET", f"{GMAIL}/messages", params={
            "q": f"in:inbox newer_than:{days}d", "maxResults": max_results})
        out = []
        for ref in listing.get("messages", []):
            m = self._request("GET", f"{GMAIL}/messages/{ref['id']}", params={"format": "full"})
            out.append(_parse_gmail(m))
        return out

    def send_message(self, to: list[str], subject: str, body: str, thread_id: str | None = None,
                     in_reply_to: str | None = None) -> str:
        msg = MimeMessage()
        msg["To"] = ", ".join(_header_safe(t) for t in to)
        msg["Subject"] = _header_safe(subject)
        if in_reply_to:
            msg["In-Reply-To"] = _header_safe(in_reply_to)
            msg["References"] = _header_safe(in_reply_to)
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        return self._request("POST", f"{GMAIL}/messages/send", json=payload).get("id", "")

    def mark_read(self, external_id: str) -> None:
        self._request("POST", f"{GMAIL}/messages/{external_id}/modify", json={"removeLabelIds": ["UNREAD"]})

    # ------------------------------------------------------------------ Calendar
    def list_events(self, start: datetime, end: datetime) -> list[dict]:
        data = self._request("GET", f"{CAL}/events", params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": 250})
        out = []
        for e in data.get("items", []):
            if e.get("status") == "cancelled":
                continue
            s, en = e.get("start", {}), e.get("end", {})
            if "dateTime" not in s:  # all-day events don't block time slots
                continue
            out.append({
                "external_id": e["id"],
                "title": e.get("summary", "(no title)")[:300],
                "description": (e.get("description") or "")[:5000],
                "location": (e.get("location") or "")[:300],
                "start": datetime.fromisoformat(s["dateTime"]),
                "end": datetime.fromisoformat(en["dateTime"]),
                "attendees": [a.get("email", "") for a in e.get("attendees", [])][:50],
            })
        return out

    def create_event(self, title: str, start: datetime, end: datetime, attendees: list[str],
                     description: str = "") -> str:
        body = {
            "summary": title, "description": description,
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()},
            "attendees": [{"email": a} for a in attendees],
        }
        params = {"sendUpdates": "all" if attendees else "none"}
        return self._request("POST", f"{CAL}/events", json=body, params=params).get("id", "")


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode() + b"===").decode("utf-8", errors="replace")


def _extract_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if mime == "text/plain" and data:
        return _decode_part(data)
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    if mime == "text/html" and data:  # strip markup; we never render remote HTML
        html = _decode_part(data)
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    return ""


def _parse_gmail(m: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
    received = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, tz=timezone.utc)
    if not m.get("internalDate") and headers.get("date"):
        received = parsedate_to_datetime(headers["date"])
    sender = headers.get("from", "")
    return {
        "external_id": m["id"],
        "thread_id": m.get("threadId"),
        "message_id_header": headers.get("message-id"),
        "sender": sender[:400],
        "sender_email": (getaddresses([sender])[0][1] if sender else "").lower(),
        "subject": headers.get("subject", "")[:500],
        "snippet": m.get("snippet", "")[:500],
        "body": _extract_text(m.get("payload", {}))[:50000],
        "received_at": received,
        "is_read": "UNREAD" not in m.get("labelIds", []),
    }
