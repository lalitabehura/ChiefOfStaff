import { useState } from "react";
import { api, fmtDateTime, notifyActionsChanged, type Action } from "./api";

const KIND_LABEL: Record<string, string> = {
  create_task: "Create task",
  complete_task: "Complete task",
  create_event: "Add to calendar",
  send_email: "Send email",
};

function Summary({ a }: { a: Action }) {
  const p = a.payload;
  switch (a.kind) {
    case "create_task":
      return <p><b>{p.title}</b>{p.due_at && <> · due {fmtDateTime(p.due_at)}</>}</p>;
    case "complete_task":
      return <p>Mark <b>{p.title || "task"}</b> as done</p>;
    case "create_event":
      return <p><b>{p.title}</b> · {fmtDateTime(p.start)} – {new Date(p.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>;
    case "send_email":
      return <p>To <b>{(p.to || []).join(", ")}</b> · {p.subject}</p>;
    default:
      return <pre>{JSON.stringify(p, null, 2)}</pre>;
  }
}

export default function ActionCard({ action, onChange }: { action: Action; onChange?: (a: Action) => void }) {
  const [a, setA] = useState(action);
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(action.payload.subject ?? "");
  const [body, setBody] = useState(action.payload.body ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function decide(approve: boolean) {
    setBusy(true);
    setError("");
    try {
      const payload = approve && editing && a.kind === "send_email" ? { ...a.payload, subject, body } : undefined;
      const updated = await api<Action>(`/agent/actions/${a.id}/${approve ? "approve" : "reject"}`, {
        method: "POST",
        body: approve ? { payload } : undefined,
      });
      setA(updated);
      setEditing(false);
      onChange?.(updated);
      notifyActionsChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`action-card status-${a.status}`}>
      <div className="action-head">
        <span className="kind">{KIND_LABEL[a.kind] || a.kind}</span>
        <span className={`status ${a.status}`}>{a.status}</span>
      </div>
      <Summary a={a} />
      {a.rationale && <small className="muted">Why: {a.rationale}</small>}
      {a.kind === "send_email" && a.status === "pending" && (
        editing ? (
          <div className="stack">
            <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
            <textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} maxLength={20000} />
          </div>
        ) : (
          <pre className="email-preview">{a.payload.body}</pre>
        )
      )}
      {a.status === "executed" && a.result?.simulated && <small className="muted">{a.result.note}</small>}
      {a.error && <p className="error">{a.error}</p>}
      {error && <p className="error">{error}</p>}
      {a.status === "pending" && (
        <div className="row">
          <button className="primary" disabled={busy} onClick={() => decide(true)}>
            {a.kind === "send_email" ? (editing ? "Send edited" : "Approve & send") : "Approve"}
          </button>
          {a.kind === "send_email" && !editing && <button disabled={busy} onClick={() => setEditing(true)}>Edit</button>}
          <button className="ghost" disabled={busy} onClick={() => decide(false)}>Dismiss</button>
        </div>
      )}
    </div>
  );
}
