# Chief of Staff — AI-Powered Personal Workflow Agent

A digital chief of staff that prioritises your tasks, protects focus time on your calendar,
triages your inbox, drafts replies, and runs your routines — learning your habits as it goes,
while **you stay in control of everything that leaves your account**.

## Features

| Area | What it does |
|---|---|
| **Daily brief** | One view of today: meetings, free time, top priorities, overdue items, emails needing a reply, pending approvals. |
| **AI assistant (chat)** | "Plan my day", "Add task send invoice tomorrow", "Schedule board report", "What should I work on?" — free-form with an Anthropic key, deterministic intent parsing without one. |
| **Approval queue** | Every side effect (task, event, email) is an *action* with a rationale. Approve, edit, or dismiss. |
| **Autonomy levels** | `Suggest` (approve everything) → `Balanced` (tasks automatic) → `Autonomous` (tasks + calendar automatic). Email **always** requires approval. |
| **Task prioritisation** | Explainable score from urgency, importance, effort ("quick win") and age, with a plain-English reason per task. |
| **Habit learning** | ▲/▼ feedback tunes priority weights and tag preferences; accepted focus slots teach preferred hours; approval statistics suggest when to grant more autonomy. Fully visible and resettable in Settings. |
| **Smart scheduling** | Free-slot search within working hours and days, meeting buffers, learned preferred hours; one-click "Find time" per task and "Plan this day". |
| **Inbox triage** | Categorises mail (urgent / action / fyi / newsletter / spam), flags phishing and prompt-injection attempts, drafts replies in your tone with your signature, converts mail to tasks. |
| **Automations** | "When email from @client.com → create task (automatically)", "subject contains invoice → label action", "→ draft reply (for approval)". |
| **Integrations** | Google Gmail + Calendar via OAuth (PKCE, least-privilege scopes, revocation on disconnect) and a demo workspace to try everything instantly. |
| **Background worker** | Syncs every 10 minutes, re-prioritises twice an hour, cleans up expired tokens nightly. |
| **Account & privacy** | MFA (TOTP + one-time recovery codes), session management, security activity log, full JSON data export, permanent account deletion. |

## Architecture

```
frontend/  React 18 + TypeScript + Vite  → served by unprivileged nginx (strict CSP, API reverse proxy)
backend/   FastAPI + SQLAlchemy 2 + Alembic
  app/api/           HTTP routes (auth, account, tasks, calendar, email, agent, rules, integrations)
  app/services/      agent, actions (approval policy), prioritizer, learning, scheduler, triage,
                     rules, sync, brief, ai (guardrails), providers/google, demo, audit, mailer
  app/worker.py      arq background jobs (Redis)
PostgreSQL · Redis (rate limiting + job queue)
```

Request flow for anything the agent wants to *do*:
`AI / rule / planner → AgentAction (schema-validated) → policy (autonomy level, kind) → pending or executed → audit log`.

## Quick start (local development)

Requirements: Python 3.12+, Node 20+.

```bash
# Backend  (SQLite, auto-created tables, in-memory rate limiting)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000          # API docs: http://localhost:8000/api/docs

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

Create an account, then click **Load demo data** on the Today page to explore with a sample
inbox (including a prompt-injection phishing email the triage flags), calendar and tasks.

Optional: `export ANTHROPIC_API_KEY=...` before starting the backend to enable AI triage,
drafting and free-form chat. Without it the app uses built-in rules — every feature still works.

Run tests: `cd backend && pytest -q` (24 tests covering auth, token rotation/reuse detection,
MFA, lockout, cross-user isolation, approval policy, header injection, prompt-injection
handling, encryption, export/delete).

## Production deployment (Docker Compose)

```bash
cp .env.example .env      # fill in SECRET_KEY, ENCRYPTION_KEY, passwords, FRONTEND_URL, hosts
docker compose up -d --build
```

The stack listens on port 8080. Put a TLS-terminating proxy (Caddy, Traefik, a cloud load
balancer) in front of it — production mode requires HTTPS and refuses to boot with insecure
settings (default secrets, wildcard hosts, SQLite, non-HTTPS URL). Migrations run automatically
on backend start (`alembic upgrade head`).

### Google integration
1. Google Cloud Console → create an OAuth client (Web application).
2. Authorised redirect URI: `https://YOUR_DOMAIN/api/v1/integrations/google/callback`.
3. Enable the Gmail API and Google Calendar API; configure the consent screen with scopes
   `gmail.modify`, `gmail.send`, `calendar.events`, `openid`, `email`.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` in `.env`.
   (Restricted Gmail scopes require Google's verification before public launch.)

### Production checklist
- [ ] Random `SECRET_KEY` (≥ 48 chars) and `ENCRYPTION_KEY` (32 bytes, base64) stored in a secret manager
- [ ] TLS in front of the stack; HSTS is sent automatically in production
- [ ] `ALLOWED_HOSTS` and `CORS_ORIGINS` set to your domain only
- [ ] SMTP configured (password-reset emails)
- [ ] Automated Postgres backups (encrypted) and a tested restore
- [ ] Centralised logs (the backend writes JSON access logs; no bodies or tokens are logged)
- [ ] Uptime checks on `/healthz` and `/readyz`
- [ ] CI green (lint, tests, `pip-audit`, `npm audit`)

## Roadmap ideas
Email verification on sign-up · Microsoft 365 / Outlook provider · Slack notifications for
approvals · mobile push for the daily brief · team / delegated-assistant mode · WebAuthn passkeys.
