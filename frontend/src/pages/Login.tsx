import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";

type Mode = "login" | "register" | "mfa" | "forgot";

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    setBusy(true);
    try {
      if (mode === "register") await register(email, password, name);
      else if (mode === "forgot") {
        await api("/auth/password/forgot", { method: "POST", body: { email } });
        setInfo("If that account exists, a reset link is on its way.");
      } else if (mode === "mfa") {
        await login(email, password, useRecovery ? { recovery_code: code } : { mfa_code: code });
      } else await login(email, password);
    } catch (err) {
      if (err instanceof ApiError && err.message === "mfa_required") setMode("mfa");
      else setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const title = { login: "Welcome back", register: "Create your account", mfa: "Two-step verification", forgot: "Reset password" }[mode];

  return (
    <div className="auth-page">
      <div className="auth-hero">
        <span className="brand-mark big">✓</span>
        <h1>Your AI chief of staff.</h1>
        <p>Prioritised tasks, a calendar that protects your focus, and an inbox that drafts its own replies — with you approving everything that leaves.</p>
      </div>
      <form className="card auth-card" onSubmit={submit}>
        <h2>{title}</h2>
        {mode === "mfa" ? (
          <>
            <label>
              {useRecovery ? "Recovery code" : "6-digit code from your authenticator"}
              <input autoFocus value={code} onChange={(e) => setCode(e.target.value.trim())}
                inputMode={useRecovery ? "text" : "numeric"} autoComplete="one-time-code" maxLength={useRecovery ? 32 : 6} required />
            </label>
            <button type="button" className="link" onClick={() => setUseRecovery(!useRecovery)}>
              {useRecovery ? "Use authenticator code" : "Use a recovery code"}
            </button>
          </>
        ) : (
          <>
            {mode === "register" && (
              <label>Full name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="name" /></label>
            )}
            <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
            {mode !== "forgot" && (
              <label>
                Password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                  minLength={mode === "register" ? 12 : 1} maxLength={128}
                  autoComplete={mode === "register" ? "new-password" : "current-password"} />
              </label>
            )}
            {mode === "register" && <p className="hint">At least 12 characters, mixing upper, lower, digits or symbols.</p>}
          </>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {info && <p className="success">{info}</p>}
        <button className="primary" disabled={busy}>
          {busy ? "Please wait…" : mode === "register" ? "Create account" : mode === "forgot" ? "Send reset link" : "Sign in"}
        </button>
        <div className="auth-links">
          {mode === "login" && (
            <>
              <button type="button" className="link" onClick={() => setMode("register")}>Create an account</button>
              <button type="button" className="link" onClick={() => setMode("forgot")}>Forgot password?</button>
            </>
          )}
          {mode !== "login" && <button type="button" className="link" onClick={() => { setMode("login"); setCode(""); }}>Back to sign in</button>}
        </div>
      </form>
    </div>
  );
}
