import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState, type FormEvent } from "react";
import { api, fmtDateTime, type AuditEntry, type Integration, type Prefs, type Session, type User } from "../api";
import { useAuth } from "../auth";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="card stack"><h3>{title}</h3>{children}</section>;
}

export default function Settings() {
  const { user, setUser, logout } = useAuth();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [available, setAvailable] = useState<{ google: boolean; ai: boolean }>({ google: false, ai: false });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [mfa, setMfa] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [disable, setDisable] = useState({ password: "", code: "" });
  const [del, setDel] = useState({ password: "", confirm: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const flash = (m: string) => { setMsg(m); setError(""); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const fail = (e: unknown) => { setError(e instanceof Error ? e.message : "Failed"); window.scrollTo({ top: 0, behavior: "smooth" }); };

  const load = () => {
    api<Prefs>("/account/preferences").then(setPrefs).catch(fail);
    api<Integration[]>("/integrations").then(setIntegrations).catch(() => {});
    api<{ google: boolean; ai: boolean }>("/integrations/available").then(setAvailable).catch(() => {});
    api<Session[]>("/auth/sessions").then(setSessions).catch(() => {});
    api<AuditEntry[]>("/account/audit-log?limit=25").then(setAudit).catch(() => {});
  };
  useEffect(() => {
    load();
    const status = new URLSearchParams(window.location.search).get("integration");
    if (status) {
      if (status === "connected") flash("Google connected. Syncing your mail and calendar…");
      else setError(`Google connection ${status.replace("_", " ")}.`);
      history.replaceState(null, "", "/settings");
      if (status === "connected") api("/integrations/sync", { method: "POST" }).then(load).catch(() => {});
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveProfile(e: FormEvent) {
    e.preventDefault();
    try {
      setUser(await api<User>("/account/me", { method: "PATCH", body: { full_name: user!.full_name, timezone: user!.timezone } }));
      const { learned: _learned, ...body } = prefs!;
      setPrefs(await api<Prefs>("/account/preferences", { method: "PUT", body }));
      flash("Saved.");
    } catch (err) { fail(err); }
  }

  async function connectGoogle() {
    try {
      const { auth_url } = await api<{ auth_url: string }>("/integrations/google/start", { method: "POST" });
      if (!auth_url.startsWith("https://accounts.google.com/")) throw new Error("Unexpected auth URL");
      window.location.assign(auth_url);
    } catch (err) { fail(err); }
  }

  const call = (fn: () => Promise<unknown>, ok: string) => fn().then(() => { flash(ok); load(); }).catch(fail);

  if (!prefs || !user) return <p className="muted">Loading…</p>;
  const learned = prefs.learned || {};

  return (
    <div className="page narrow">
      <header className="page-head"><div><p className="eyebrow">Account, privacy & security</p><h1>Settings</h1></div></header>
      {msg && <p className="success" onClick={() => setMsg("")}>{msg}</p>}
      {error && <p className="error" onClick={() => setError("")}>{error}</p>}

      <form onSubmit={saveProfile} className="stack">
        <Section title="Profile & working style">
          <div className="row wrap">
            <label className="grow">Name<input value={user.full_name} maxLength={120} onChange={(e) => setUser({ ...user, full_name: e.target.value })} /></label>
            <label className="grow">Timezone<input value={user.timezone} maxLength={64} onChange={(e) => setUser({ ...user, timezone: e.target.value })} /></label>
          </div>
          <div className="row wrap">
            <label>Work starts<input type="time" value={prefs.work_start} onChange={(e) => setPrefs({ ...prefs, work_start: e.target.value })} /></label>
            <label>Work ends<input type="time" value={prefs.work_end} onChange={(e) => setPrefs({ ...prefs, work_end: e.target.value })} /></label>
            <label>Meeting buffer (min)<input type="number" min={0} max={60} value={prefs.meeting_buffer_minutes} onChange={(e) => setPrefs({ ...prefs, meeting_buffer_minutes: +e.target.value })} /></label>
            <label>Focus block (min)<input type="number" min={15} max={240} value={prefs.focus_block_minutes} onChange={(e) => setPrefs({ ...prefs, focus_block_minutes: +e.target.value })} /></label>
          </div>
          <div className="row wrap days">
            {DAYS.map((d, i) => (
              <label key={d} className="check">
                <input type="checkbox" checked={prefs.work_days.includes(i)}
                  onChange={(e) => setPrefs({ ...prefs, work_days: e.target.checked ? [...prefs.work_days, i] : prefs.work_days.filter((x) => x !== i) })} />{d}
              </label>
            ))}
          </div>
        </Section>

        <Section title="Assistant autonomy">
          <div className="radio-cards">
            {([
              ["suggest", "Suggest", "Everything is a suggestion you approve."],
              ["balanced", "Balanced", "Creates/completes tasks on its own; asks before calendar changes."],
              ["auto", "Autonomous", "Handles tasks and calendar on its own."],
            ] as const).map(([v, label, desc]) => (
              <label key={v} className={`radio-card ${prefs.autonomy_level === v ? "on" : ""}`}>
                <input type="radio" name="autonomy" checked={prefs.autonomy_level === v} onChange={() => setPrefs({ ...prefs, autonomy_level: v })} />
                <strong>{label}</strong><small>{desc}</small>
              </label>
            ))}
          </div>
          <p className="hint">🔒 Emails are never sent without your explicit approval, at any autonomy level.</p>
          <div className="row wrap">
            <label>Reply tone
              <select value={prefs.reply_tone} onChange={(e) => setPrefs({ ...prefs, reply_tone: e.target.value as Prefs["reply_tone"] })}>
                <option value="professional">Professional</option><option value="friendly">Friendly</option><option value="concise">Concise</option>
              </select>
            </label>
            <label className="grow">Signature<input value={prefs.signature} maxLength={500} onChange={(e) => setPrefs({ ...prefs, signature: e.target.value })} /></label>
          </div>
          <button className="primary">Save settings</button>
        </Section>
      </form>

      <Section title="What your assistant has learned">
        <p className="muted">Learned only from your feedback and approvals — never from message contents.</p>
        <div className="kv">
          <span>Priority weights</span>
          <span>{Object.entries(learned.priority_weights || {}).map(([k, v]) => `${k} ${Math.round(Number(v) * 100)}%`).join(" · ") || "defaults"}</span>
          <span>Tag preferences</span>
          <span>{Object.entries(learned.tag_boosts || {}).map(([k, v]) => `${k} ${Number(v) > 0 ? "↑" : "↓"}`).join(" · ") || "none yet"}</span>
          <span>Preferred focus hours</span>
          <span>{Object.keys(learned.focus_hours || {}).map((h) => `${h}:00`).join(", ") || "none yet"}</span>
        </div>
        <button className="ghost" onClick={() => call(() => api("/account/preferences/reset-learning", { method: "POST" }), "Learning reset.")}>Reset learning</button>
      </Section>

      <Section title="Connected accounts">
        {integrations.map((i) => (
          <div key={i.provider} className="row between">
            <div><strong>{i.provider === "google" ? "Google (Gmail + Calendar)" : "Demo workspace"}</strong>
              <small className="muted block">{i.account_email} · {i.status}{i.last_synced_at && ` · synced ${fmtDateTime(i.last_synced_at)}`}</small></div>
            <button className="ghost" onClick={() => confirm("Disconnect? Access will be revoked.") && call(() => api(`/integrations/${i.provider}`, { method: "DELETE" }), "Disconnected.")}>Disconnect</button>
          </div>
        ))}
        <div className="row">
          {!integrations.some((i) => i.provider === "google") && (
            <button className="primary" onClick={connectGoogle} disabled={!available.google} title={available.google ? "" : "Server admin must configure Google OAuth"}>Connect Google</button>
          )}
          {!integrations.some((i) => i.provider === "demo") && <button onClick={() => call(() => api("/integrations/demo/connect", { method: "POST" }), "Demo data loaded.")}>Load demo workspace</button>}
        </div>
        <small className="muted">AI drafting: {available.ai ? "enabled" : "using built-in rules (no AI key configured)"}. Requested Google scopes: read/label mail, send mail, manage calendar events.</small>
      </Section>

      <Section title="Two-factor authentication">
        {user.mfa_enabled ? (
          <>
            <p className="success">✓ Enabled</p>
            <div className="row wrap">
              <input type="password" placeholder="Password" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} />
              <input placeholder="6-digit code" value={disable.code} maxLength={6} onChange={(e) => setDisable({ ...disable, code: e.target.value })} />
              <button className="ghost" onClick={() => call(async () => { await api("/auth/mfa/disable", { method: "POST", body: disable }); setUser({ ...user, mfa_enabled: false }); }, "Two-factor disabled.")}>Disable</button>
            </div>
          </>
        ) : mfa ? (
          <>
            <p>Scan with an authenticator app, then enter the code.</p>
            <div className="qr"><QRCodeSVG value={mfa.otpauth_uri} size={168} /></div>
            <small className="muted">Or enter manually: <code>{mfa.secret}</code></small>
            <div className="row">
              <input placeholder="123456" value={mfaCode} maxLength={6} inputMode="numeric" onChange={(e) => setMfaCode(e.target.value)} />
              <button className="primary" onClick={() => api<{ recovery_codes: string[] }>("/auth/mfa/enable", { method: "POST", body: { code: mfaCode } })
                .then((r) => { setRecovery(r.recovery_codes); setMfa(null); setUser({ ...user, mfa_enabled: true }); }).catch(fail)}>Verify & enable</button>
            </div>
          </>
        ) : (
          <button className="primary" onClick={() => api<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST" }).then(setMfa).catch(fail)}>Set up authenticator app</button>
        )}
        {recovery && (
          <div className="recovery">
            <strong>Save these recovery codes now — they won't be shown again.</strong>
            <pre>{recovery.join("\n")}</pre>
            <button onClick={() => setRecovery(null)}>I've saved them</button>
          </div>
        )}
      </Section>

      <Section title="Password">
        <div className="row wrap">
          <input type="password" placeholder="Current password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <input type="password" placeholder="New password (12+ chars)" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <button onClick={() => api("/auth/password/change", { method: "POST", body: { current_password: pw.current, new_password: pw.next } })
            .then(() => { alert("Password changed. Please sign in again."); logout(); }).catch(fail)}>Change password</button>
        </div>
      </Section>

      <Section title="Active sessions">
        {sessions.map((s) => (
          <div key={s.id} className="row between">
            <div><strong>{s.current ? "This device" : s.user_agent.slice(0, 60) || "Unknown device"}</strong>
              <small className="muted block">{s.ip} · signed in {fmtDateTime(s.created_at)}</small></div>
            {!s.current && <button className="ghost" onClick={() => call(() => api(`/auth/sessions/${s.id}`, { method: "DELETE" }), "Session revoked.")}>Revoke</button>}
          </div>
        ))}
        <button className="ghost" onClick={() => api("/auth/logout-all", { method: "POST" }).then(logout).catch(fail)}>Sign out everywhere</button>
      </Section>

      <Section title="Security activity">
        <div className="audit">
          {audit.map((a) => <div key={a.id}><span>{fmtDateTime(a.created_at)}</span><span>{a.action}</span><span className="muted">{a.ip}</span></div>)}
        </div>
      </Section>

      <Section title="Your data">
        <div className="row">
          <button onClick={async () => {
            try {
              const data = await api("/account/export");
              const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
              const a = document.createElement("a");
              a.href = url; a.download = "chief-of-staff-export.json"; a.click();
              URL.revokeObjectURL(url);
            } catch (err) { fail(err); }
          }}>Export all my data</button>
        </div>
        <div className="danger stack">
          <strong>Delete account</strong>
          <small>Permanently deletes your data and revokes connected-account access.</small>
          <div className="row wrap">
            <input type="password" placeholder="Password" value={del.password} onChange={(e) => setDel({ ...del, password: e.target.value })} />
            <input placeholder='Type "DELETE"' value={del.confirm} onChange={(e) => setDel({ ...del, confirm: e.target.value })} />
            <button className="danger-btn" disabled={del.confirm !== "DELETE"} onClick={() => api("/account", { method: "DELETE", body: del }).then(logout).catch(fail)}>Delete forever</button>
          </div>
        </div>
      </Section>
    </div>
  );
}
