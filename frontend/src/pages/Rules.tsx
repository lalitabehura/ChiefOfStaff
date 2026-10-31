import { useEffect, useState, type FormEvent } from "react";
import { api, type Rule } from "../api";

const blank = { name: "", field: "from_contains", value: "", action: "create_task", category: "action", importance: 3, instructions: "", autonomy: "suggest" };

const describe = (r: Rule) => {
  const c = Object.entries(r.conditions).map(([k, v]) => `${k.replace("_", " ")} "${v}"`).join(" and ");
  const a = r.action.type === "set_category" ? `label as ${r.action.category}`
    : r.action.type === "create_task" ? `create a task (importance ${r.action.importance})`
    : r.action.type === "draft_reply" ? "draft a reply for approval" : "mark as read";
  return `When email ${c} → ${a}`;
};

export default function Rules() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [f, setF] = useState(blank);
  const [error, setError] = useState("");

  const load = () => api<Rule[]>("/rules").then(setRules).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/rules", {
        method: "POST",
        body: {
          name: f.name,
          conditions: f.field === "category" ? { category: f.value } : { [f.field]: f.value },
          action: { type: f.action, category: f.action === "set_category" ? f.category : undefined, importance: f.importance, instructions: f.instructions },
          autonomy: f.autonomy,
        },
      });
      setF(blank);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  async function toggle(r: Rule) {
    await api(`/rules/${r.id}`, { method: "PUT", body: { ...r, enabled: !r.enabled } });
    load();
  }

  return (
    <div className="page">
      <header className="page-head"><div><p className="eyebrow">Teach it your routines</p><h1>Automations</h1></div></header>
      <form className="card stack" onSubmit={create}>
        <h3>New rule</h3>
        <input placeholder="Rule name, e.g. 'Client mail becomes tasks'" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required maxLength={100} />
        <div className="row wrap">
          <span>When email</span>
          <select value={f.field} onChange={(e) => setF({ ...f, field: e.target.value, value: "" })}>
            <option value="from_contains">sender contains</option>
            <option value="subject_contains">subject contains</option>
            <option value="body_contains">body contains</option>
            <option value="category">is categorised as</option>
          </select>
          {f.field === "category" ? (
            <select value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} required>
              <option value="">choose…</option>
              {["urgent", "action", "fyi", "newsletter", "spam"].map((c) => <option key={c}>{c}</option>)}
            </select>
          ) : (
            <input value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} required maxLength={200} placeholder="@client.com" />
          )}
        </div>
        <div className="row wrap">
          <span>then</span>
          <select value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}>
            <option value="create_task">create a task</option>
            <option value="set_category">set category</option>
            <option value="mark_read">mark as read</option>
            <option value="draft_reply">draft a reply (always needs approval)</option>
          </select>
          {f.action === "set_category" && (
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
              {["urgent", "action", "fyi", "newsletter", "spam"].map((c) => <option key={c}>{c}</option>)}
            </select>
          )}
          {f.action === "create_task" && (
            <>
              <select value={f.importance} onChange={(e) => setF({ ...f, importance: +e.target.value })}>
                {[1, 2, 3, 4, 5].map((i) => <option key={i} value={i}>importance {i}</option>)}
              </select>
              <select value={f.autonomy} onChange={(e) => setF({ ...f, autonomy: e.target.value })}>
                <option value="suggest">ask me first</option>
                <option value="auto">do it automatically</option>
              </select>
            </>
          )}
        </div>
        {f.action === "draft_reply" && <input placeholder="Reply guidance" value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} maxLength={500} />}
        {error && <p className="error">{error}</p>}
        <button className="primary">Create rule</button>
      </form>

      <div className="card table">
        {rules.length === 0 && <p className="muted pad">No automations yet.</p>}
        {rules.map((r) => (
          <div key={r.id} className="task-row">
            <input type="checkbox" checked={r.enabled} onChange={() => toggle(r)} aria-label="Enabled" />
            <div className="grow">
              <div className="task-title">{r.name}</div>
              <small className="muted">{describe(r)} · {r.autonomy === "auto" ? "automatic" : "asks first"} · fired {r.times_fired}×</small>
            </div>
            <button className="ghost" onClick={async () => { await api(`/rules/${r.id}`, { method: "DELETE" }); load(); }}>Delete</button>
          </div>
        ))}
      </div>
    </div>
  );
}
