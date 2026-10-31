// API client. The access token lives only in memory (never localStorage) so XSS cannot
// persist-steal it; the refresh token is an HttpOnly, SameSite=Strict cookie the JS can't read.
const BASE = "/api/v1";
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionLost: (() => void) | null = null;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function setSessionLostHandler(fn: () => void) {
  onSessionLost = fn;
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
  }
  return fallback;
}

export async function refreshSession(): Promise<TokenOut | null> {
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
  if (!res.ok) return null;
  const data = (await res.json()) as TokenOut;
  accessToken = data.access_token;
  return data;
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) refreshing = refreshSession().then((d) => !!d).finally(() => (refreshing = null));
  return refreshing;
}

type Opts = { method?: string; body?: unknown; retry?: boolean };

export async function api<T = unknown>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, retry = true } = opts;
  const headers: Record<string, string> = { "X-Requested-With": "XMLHttpRequest" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await tryRefresh()) return api<T>(path, { ...opts, retry: false });
    accessToken = null;
    onSessionLost?.();
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  return data as T;
}

// ---------------------------------------------------------------- types
export interface User { id: string; email: string; full_name: string; timezone: string; mfa_enabled: boolean; created_at: string }
export interface TokenOut { access_token: string; expires_in: number; user: User }
export interface Task {
  id: string; title: string; description: string; due_at: string | null; estimate_minutes: number;
  importance: number; status: "todo" | "in_progress" | "done"; tags: string[]; priority_score: number;
  priority_reason: string; source: string; scheduled_start: string | null; created_at: string; completed_at: string | null;
}
export interface CalEvent { id: string; title: string; description: string; location: string; start: string; end: string; attendees: string[]; source: string; is_focus_block: boolean; task_id: string | null }
export interface Email { id: string; sender: string; subject: string; snippet: string; received_at: string; category: string; triage_reason: string; needs_reply: boolean; is_read: boolean; body?: string | null }
export interface Action { id: string; kind: string; payload: Record<string, any>; status: string; rationale: string; confidence: number; source: string; error: string | null; result: Record<string, any>; created_at: string }
export interface Message { id: string; role: "user" | "assistant"; content: string; created_at: string }
export interface Rule { id: string; name: string; trigger: string; conditions: Record<string, string>; action: Record<string, any>; autonomy: string; enabled: boolean; times_fired: number }
export interface Prefs { work_start: string; work_end: string; work_days: number[]; focus_block_minutes: number; meeting_buffer_minutes: number; autonomy_level: "suggest" | "balanced" | "auto"; reply_tone: "professional" | "friendly" | "concise"; signature: string; daily_brief_enabled: boolean; learned: Record<string, any> }
export interface Integration { provider: string; account_email: string; status: string; connected_at: string; last_synced_at: string | null }
export interface Session { id: string; created_at: string; user_agent: string; ip: string; current: boolean }
export interface AuditEntry { id: number; action: string; ip: string; user_agent: string; meta: Record<string, unknown>; created_at: string }
export interface Brief {
  summary: string; date: string; events: CalEvent[]; top_tasks: Task[]; overdue_count: number;
  emails_needing_reply: Email[]; pending_approvals: number; free_minutes: number; meeting_minutes: number; tips: string[];
}

// ---------------------------------------------------------------- formatting helpers
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
export const fmtDateTime = (iso: string) => `${fmtDate(iso)} ${fmtTime(iso)}`;

export const notifyActionsChanged = () => window.dispatchEvent(new Event("cos:actions-changed"));
