"""Request/response schemas. Strict length limits on every input field."""
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _check_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except Exception as exc:
        raise ValueError("Unknown timezone") from exc
    return v


# --------------------------------------------------------------------------- auth
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    _tz = field_validator("timezone")(_check_tz)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    mfa_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recovery_code: str | None = Field(default=None, max_length=32)


class UserOut(ORM):
    id: str
    email: str
    full_name: str
    timezone: str
    mfa_enabled: bool
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class PasswordForgotIn(BaseModel):
    email: EmailStr


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class SessionOut(BaseModel):
    id: str
    created_at: datetime
    user_agent: str
    ip: str
    current: bool


# --------------------------------------------------------------------------- account
class MeUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        return _check_tz(v) if v else v


class PreferencesIn(BaseModel):
    work_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    work_days: list[int] = Field(min_length=1, max_length=7)
    focus_block_minutes: int = Field(ge=15, le=240)
    meeting_buffer_minutes: int = Field(ge=0, le=60)
    autonomy_level: Literal["suggest", "balanced", "auto"]
    reply_tone: Literal["professional", "friendly", "concise"]
    signature: str = Field(default="", max_length=500)
    daily_brief_enabled: bool = True

    @field_validator("work_days")
    @classmethod
    def _days(cls, v):
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("work_days must be 0 (Mon) .. 6 (Sun)")
        return sorted(set(v))

    @model_validator(mode="after")
    def _order(self):
        if self.work_end <= self.work_start:
            raise ValueError("work_end must be after work_start")
        return self


class PreferencesOut(PreferencesIn, ORM):
    learned: dict = {}


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)
    confirm: Literal["DELETE"]


class AuditOut(ORM):
    id: int
    action: str
    ip: str
    user_agent: str
    meta: dict
    created_at: datetime


# --------------------------------------------------------------------------- tasks
TaskStatus = Literal["todo", "in_progress", "done"]
Tag = Field(min_length=1, max_length=32)


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    due_at: datetime | None = None
    estimate_minutes: int = Field(default=30, ge=5, le=480)
    importance: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=10)
    status: TaskStatus = "todo"


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    due_at: datetime | None = None
    estimate_minutes: int | None = Field(default=None, ge=5, le=480)
    importance: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = Field(default=None, max_length=10)
    status: TaskStatus | None = None


class TaskOut(ORM):
    id: str
    title: str
    description: str
    due_at: datetime | None
    estimate_minutes: int
    importance: int
    status: str
    tags: list[str]
    priority_score: float
    priority_reason: str
    source: str
    scheduled_start: datetime | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TaskFeedbackIn(BaseModel):
    signal: Literal["more_important", "less_important"]


# --------------------------------------------------------------------------- calendar
class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    location: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if (self.end - self.start).days > 7:
            raise ValueError("events longer than 7 days are not supported")
        return self


class EventOut(ORM):
    id: str
    title: str
    description: str
    location: str
    start: datetime
    end: datetime
    attendees: list[str]
    source: str
    is_focus_block: bool
    task_id: str | None


class SlotOut(BaseModel):
    start: datetime
    end: datetime


# --------------------------------------------------------------------------- email
EmailCategory = Literal["urgent", "action", "fyi", "newsletter", "spam", "unsorted"]


class EmailOut(ORM):
    id: str
    sender: str
    subject: str
    snippet: str
    received_at: datetime
    category: str
    triage_reason: str
    needs_reply: bool
    is_read: bool
    thread_id: str | None


class EmailDetail(EmailOut):
    body: str | None


class DraftIn(BaseModel):
    instructions: str = Field(default="", max_length=1000)


# --------------------------------------------------------------------------- agent
class ActionOut(ORM):
    id: str
    kind: str
    payload: dict
    status: str
    rationale: str
    confidence: float
    source: str
    error: str | None
    result: dict
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None


class ApproveIn(BaseModel):
    payload: dict | None = None  # optionally edited payload; re-validated per action kind


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    reply: str
    actions: list[ActionOut]


class MessageOut(ORM):
    id: str
    role: str
    content: str
    created_at: datetime


# --------------------------------------------------------------------------- rules
class RuleConditions(BaseModel):
    from_contains: str | None = Field(default=None, max_length=200)
    subject_contains: str | None = Field(default=None, max_length=200)
    body_contains: str | None = Field(default=None, max_length=200)
    category: EmailCategory | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not any([self.from_contains, self.subject_contains, self.body_contains, self.category]):
            raise ValueError("At least one condition is required")
        return self


class RuleAction(BaseModel):
    type: Literal["create_task", "set_category", "mark_read", "draft_reply"]
    category: EmailCategory | None = None
    importance: int = Field(default=3, ge=1, le=5)
    instructions: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _category_needed(self):
        if self.type == "set_category" and not self.category:
            raise ValueError("set_category requires a category")
        return self


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    trigger: Literal["email_received"] = "email_received"
    conditions: RuleConditions
    action: RuleAction
    autonomy: Literal["suggest", "auto"] = "suggest"
    enabled: bool = True


class RuleOut(ORM):
    id: str
    name: str
    trigger: str
    conditions: dict
    action: dict
    autonomy: str
    enabled: bool
    times_fired: int
    created_at: datetime


# --------------------------------------------------------------------------- integrations
class IntegrationOut(ORM):
    provider: str
    account_email: str
    scopes: str
    status: str
    connected_at: datetime
    last_synced_at: datetime | None
