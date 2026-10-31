import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function ResetPassword() {
  // Token is in the URL fragment, which browsers never send to servers or put in Referer headers.
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw !== pw2) return setError("Passwords don't match.");
    try {
      await api("/auth/password/reset", { method: "POST", body: { token, new_password: pw } });
      history.replaceState(null, "", "/reset-password");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  }

  return (
    <div className="auth-page single">
      <form className="card auth-card" onSubmit={submit}>
        <h2>Choose a new password</h2>
        {done ? (
          <p className="success">Password updated. All other sessions were signed out. <Link to="/login">Sign in</Link></p>
        ) : !token ? (
          <p className="error">This reset link is invalid. Request a new one from the sign-in page.</p>
        ) : (
          <>
            <label>New password<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} minLength={12} maxLength={128} required autoComplete="new-password" /></label>
            <label>Confirm<input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required autoComplete="new-password" /></label>
            {error && <p className="error">{error}</p>}
            <button className="primary">Update password</button>
          </>
        )}
      </form>
    </div>
  );
}
