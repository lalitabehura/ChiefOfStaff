import { useEffect, useState, type FormEvent } from "react";
import { api, fmtDateTime, notifyActionsChanged, type Action, type Task } from "../api";

const empty = { title: "", due: "", importance: 3, estimate: 30, tags: "" };

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filter, setFilter] = useState<"open" | "done">("open");
  const [form, setForm] = useState(empty);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => api<Task[]>(`/tasks?status=${filter}`).then(setTasks).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/tasks", {
        method: "POST",
        body: {
          title: form.title,
          due_at: form.due ? new Date(form.due).toISOString() : null,
          importance: form.importance,
          estimate_minutes: form.estimate,
          tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
        },
      });
      setForm(empty);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  const act = async (fn: () => Promise<unknown>, note?: string) => {
    setError("");
    try {
      await fn();
      if (note) setMsg(note);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  };

  async function schedule(t: Task) {
    act(async () => {
      const a = await api<Action>(`/tasks/${t.id}/schedule`, { method: "POST" });
      notifyActionsChanged();
      setMsg(a.status === "executed" ? `Scheduled "${t.title}".` : `Proposed a time for "${t.title}" — approve it in Assistant.`);
    });
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><p className="eyebrow">Ranked by urgency, importance and your habits</p><h1>Tasks</h1></div>
        <div className="row">
          <div className="seg">
            <button className={filter === "open" ? "on" : ""} onClick={() => setFilter("open")}>Open</button>
            <button className={filter === "done" ? "on" : ""} onClick={() => setFilter("done")}>Done</button>
          </div>
          <button onClick={() => act(() => api("/tasks/prioritize", { method: "POST" }), "Re-prioritised.")}>Re-prioritise</button>
        </div>
      </header>

      <form className="card inline-form" onSubmit={create}>
        <input placeholder="New task" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} maxLength={200} required />
        <input type="datetime-local" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} title="Due" />
        <select value={form.importance} onChange={(e) => setForm({ ...form, importance: +e.target.value })} title="Importance">
          {[1, 2, 3, 4, 5].map((i) => <option key={i} value={i}>Importance {i}</option>)}
        </select>
        <select value={form.estimate} onChange={(e) => setForm({ ...form, estimate: +e.target.value })} title="Estimate">
          {[15, 30, 45, 60, 90, 120, 180, 240].map((m) => <option key={m} value={m}>{m} min</option>)}
        </select>
        <input placeholder="tags, comma separated" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        <button className="primary">Add</button>
      </form>

      {msg && <p className="success" onClick={() => setMsg("")}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="card table">
        {tasks.length === 0 && <p className="muted pad">No tasks here.</p>}
        {tasks.map((t) => (
          <div key={t.id} className={`task-row ${t.status}`}>
            <input type="checkbox" checked={t.status === "done"} aria-label="Done"
              onChange={() => act(() => api(`/tasks/${t.id}`, { method: "PATCH", body: { status: t.status === "done" ? "todo" : "done" } }))} />
            <span className="score" title="Priority score">{Math.round(t.priority_score)}</span>
            <div className="grow">
              <div className="task-title">{t.title}</div>
              <small className="muted">
                {t.priority_reason}
                {t.due_at && <> · due {fmtDateTime(t.due_at)}</>} · {t.estimate_minutes} min
                {t.scheduled_start && <> · 📅 {fmtDateTime(t.scheduled_start)}</>}
                {t.tags.map((g) => <span key={g} className="tag">{g}</span>)}
              </small>
            </div>
            {t.status !== "done" && (
              <div className="row tight">
                <button className="icon" title="Should be higher — teaches your assistant"
                  onClick={() => act(() => api(`/tasks/${t.id}/feedback`, { method: "POST", body: { signal: "more_important" } }), "Got it — I'll weigh tasks like this higher.")}>▲</button>
                <button className="icon" title="Should be lower — teaches your assistant"
                  onClick={() => act(() => api(`/tasks/${t.id}/feedback`, { method: "POST", body: { signal: "less_important" } }), "Got it — I'll weigh tasks like this lower.")}>▼</button>
                {!t.scheduled_start && <button onClick={() => schedule(t)}>Find time</button>}
                <button className="ghost" onClick={() => confirm(`Delete "${t.title}"?`) && act(() => api(`/tasks/${t.id}`, { method: "DELETE" }))}>Delete</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
