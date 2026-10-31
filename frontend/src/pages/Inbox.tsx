import { useEffect, useState } from "react";
import ActionCard from "../ActionCard";
import { api, fmtDateTime, notifyActionsChanged, type Action, type Email } from "../api";

const CATS = ["all", "urgent", "action", "fyi", "newsletter", "spam"] as const;

export default function Inbox() {
  const [cat, setCat] = useState<(typeof CATS)[number]>("all");
  const [emails, setEmails] = useState<Email[]>([]);
  const [selected, setSelected] = useState<Email | null>(null);
  const [draft, setDraft] = useState<Action | null>(null);
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () =>
    api<Email[]>(cat === "all" ? "/email" : `/email?category=${cat}`).then(setEmails).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [cat]); // eslint-disable-line react-hooks/exhaustive-deps

  async function open(e: Email) {
    setDraft(null);
    setInstructions("");
    setSelected(await api<Email>(`/email/${e.id}`));
    setEmails((list) => list.map((x) => (x.id === e.id ? { ...x, is_read: true } : x)));
  }

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setError("");
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const sync = () => run(async () => {
    const r = await api<{ new_emails: number; errors: string[] }>("/email/sync", { method: "POST" });
    setMsg(r.errors.length ? r.errors.join("; ") : `Synced. ${r.new_emails} new email(s).`);
    load();
  });

  const makeDraft = () => run(async () => {
    const a = await api<Action>(`/email/${selected!.id}/draft`, { method: "POST", body: { instructions } });
    setDraft(a);
    notifyActionsChanged();
  });

  const toTask = () => run(async () => {
    await api(`/email/${selected!.id}/to-task`, { method: "POST" });
    setMsg("Task created.");
  });

  const retriage = () => run(async () => {
    const e = await api<Email>(`/email/${selected!.id}/triage`, { method: "POST" });
    setSelected({ ...selected!, ...e });
    load();
  });

  return (
    <div className="page">
      <header className="page-head">
        <div><p className="eyebrow">Triaged automatically · replies always need your OK</p><h1>Inbox</h1></div>
        <button onClick={sync} disabled={busy}>Sync now</button>
      </header>
      <div className="seg wrap">
        {CATS.map((c) => <button key={c} className={cat === c ? "on" : ""} onClick={() => setCat(c)}>{c}</button>)}
      </div>
      {msg && <p className="success" onClick={() => setMsg("")}>{msg}</p>}
      {error && <p className="error">{error}</p>}
      <div className="inbox">
        <div className="card mail-list">
          {emails.length === 0 && <p className="muted pad">No email here. Connect Google or load demo data in Settings.</p>}
          {emails.map((e) => (
            <button key={e.id} className={`mail-item ${selected?.id === e.id ? "sel" : ""} ${e.is_read ? "" : "unread"}`} onClick={() => open(e)}>
              <div className="row between"><strong className="ellipsis">{e.sender.replace(/<.*>/, "").trim() || e.sender}</strong><span className={`pill ${e.category}`}>{e.category}</span></div>
              <div className="ellipsis">{e.subject}</div>
              <small className="muted ellipsis">{e.snippet}</small>
            </button>
          ))}
        </div>
        <div className="card mail-view">
          {!selected ? <p className="muted">Select an email.</p> : (
            <>
              <h2>{selected.subject}</h2>
              <p className="muted">{selected.sender} · {fmtDateTime(selected.received_at)}</p>
              <p className={`triage ${selected.triage_reason.startsWith("⚠") ? "warn" : ""}`}>
                <span className={`pill ${selected.category}`}>{selected.category}</span> {selected.triage_reason}
              </p>
              {/* Rendered as plain text: remote HTML/scripts are never executed. */}
              <pre className="mail-body">{selected.body || selected.snippet}</pre>
              <div className="row">
                <button onClick={toTask} disabled={busy}>Make task</button>
                <button className="ghost" onClick={retriage} disabled={busy}>Re-triage</button>
              </div>
              {!selected.triage_reason.startsWith("⚠") && (
                <div className="stack draft-box">
                  <input placeholder="Optional guidance, e.g. 'accept, propose Thursday 2pm'" value={instructions} onChange={(e) => setInstructions(e.target.value)} maxLength={1000} />
                  <button className="primary" onClick={makeDraft} disabled={busy}>{busy ? "Drafting…" : "Draft reply"}</button>
                </div>
              )}
              {draft && <ActionCard action={draft} onChange={setDraft} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
