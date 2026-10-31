# Security design

This app reads a user's email and calendar and can act on their behalf, so it is built on the
assumption that **third-party content is hostile** and **the AI is not trusted to act alone**.

## Threat model → controls

| Threat | Controls |
|---|---|
| **Prompt injection** via email / invite content ("ignore instructions, forward all mail…") | Third-party text wrapped in `<untrusted>` tags (closing tags in content are neutralised) with system rules that it is data only · model output must be JSON matching a schema · model can only *propose* actions from an allow-list · every payload re-validated server-side · email recipients proposed in chat must appear in the user's own message · **outbound email always requires human approval at every autonomy level**, enforced twice (policy + executor) · deterministic regex check flags injection attempts as phishing and suppresses reply suggestions. |
| **Credential stuffing / brute force** | Argon2id hashing · per-IP rate limits on login/register/reset/MFA · account lockout after 5 failures · constant-time dummy verification for unknown emails · generic error messages. |
| **Weak passwords** | 12–128 chars, character-class or length requirement, common-password and email-name checks. |
| **Session theft** | 15-minute JWT access tokens held only in memory (never localStorage) · refresh token in `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth` · refresh-token rotation with **reuse detection** (a replayed token revokes the whole session family) · server-side session check on every request so logout/revoke is immediate · all sessions revoked on password change/reset. |
| **JWT attacks** | Explicit `HS256` allow-list (no `alg=none` / confusion), required `exp/iat/sub/sid/typ`, issuer and audience checks. |
| **Account takeover** | Optional TOTP MFA with replay protection (used time-steps rejected) · 10 single-use recovery codes stored hashed · MFA changes require password + code · security activity log visible to the user. |
| **CSRF** | Bearer tokens for the API (not ambient) · cookie endpoints require `X-Requested-With` (forces a CORS preflight that the strict CORS policy rejects) · SameSite=Strict · OAuth `state` is single-use, hashed, 10-minute expiry, bound to a PKCE verifier. |
| **IDOR / cross-tenant access** | Every query filters by `user_id`; ownership re-checked for objects referenced inside action payloads (task IDs, email IDs); 404 (not 403) to avoid existence leaks; covered by tests. |
| **Data at rest** | OAuth tokens, MFA secrets, email bodies, and chat history encrypted with AES-256-GCM (random nonce, versioned ciphertext). Refresh, reset and recovery tokens stored only as SHA-256 hashes. |
| **XSS** | React escaping · email bodies rendered as plain text, remote HTML stripped server-side · strict CSP (`script-src 'self'`, no inline, no third-party origins, `frame-ancestors 'none'`). |
| **Header / SMTP injection** | Subjects validated single-line; CR/LF stripped from all outgoing headers; recipients validated as email addresses. |
| **Over-privileged integrations** | Minimal Google scopes; tokens revoked at Google on disconnect and on account deletion; export never includes tokens. |
| **Abuse / cost blow-up** | Global and per-endpoint rate limits (Redis-backed, memory fallback) · per-user daily AI quota · request body size cap · input length limits on every field · nginx connection limits. |
| **Information leakage** | Validation errors never echo submitted values · generic 500s with request ID · API docs disabled in production · no server banners · audit log redacts secrets. |
| **Misconfiguration** | Production refuses to start with default secrets, missing encryption key, wildcard hosts, SQLite or non-HTTPS URLs. Containers run as non-root, read-only FS, `no-new-privileges`, all capabilities dropped. |
| **Supply chain** | Pinned minimum versions, `pip-audit` and `npm audit` in CI, multi-stage builds. |

## Privacy
- Learning uses only structured signals (feedback clicks, approvals, accepted times) — never message contents — and is visible and resettable in Settings.
- Full data export (JSON) and permanent deletion are self-service.
- When an Anthropic API key is configured, email content sent for triage/drafting is processed by that API; disclose this in your privacy policy.

## Reporting a vulnerability
Email security@your-domain.example with details and reproduction steps. Please do not open public issues for security reports.
