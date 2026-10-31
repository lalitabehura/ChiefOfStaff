import { useEffect, useState, type FormEvent } from "react";
import { api, fmtTime, notifyActionsChanged, type Action, type CalEvent } from "../api";

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local time

export default function Calendar() {
  const [day, setDay] = useState(today());
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [slots, setSlots] = useState<{ start: string; end: string }[]>([]);
  const [form, setForm] = useState({ title: "", start: "", end: "", attendees: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => {
    api<CalEvent[]>(`/calendar/events?day=${day}`).then(setEvents).catch((e) => setError(e.message));
    api<{ start: string; end: string }[]>(`/calendar/free-slots?day=${day}&min_minutes=30`).then(setSlots).catch(() => setSlots([]));
  };
  useEffect(load, [day]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/calendar/events", {
        method: "POST",
        body: {
          title: form.title,
          start: new Date(`${day}T${form.start}`).toISOString(),
          end: new Date(`${day}T${form.end}`).toISOString(),
          attendees: form.attendees.split(",").map((a) => a.trim()).filter(Boolean),
        },
      });
      setForm({ title: "", start: "", end: "", attendees: "" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  async function planDay() {
    setError("");
    try {
      const acts = await api<Action[]>(`/calendar/plan-day?day=${day}`, { method: "POST" });
      notifyActionsChanged();
      const pending = acts.filter((a) => a.status === "pending").length;
      setMsg(acts.length === 0 ? "No room for more focus blocks today."
        : pending ? `Proposed ${pending} focus block(s) — review them in Assistant.` : `Scheduled ${acts.length} focus block(s).`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  async function remove(ev: CalEvent) {
    if (!confirm(`Delete "${ev.title}"?`)) return;
    try {
      await api(`/calendar/events/${ev.id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><p className="eyebrow">Meetings, focus time and free slots</p><h1>Calendar</h1></div>
        <div className="row">
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          <button className="primary" onClick={planDay}>Plan this day</button>
        </div>
      </header>
      {msg && <p className="success" onClick={() => setMsg("")}>{msg}</p>}
      {error && <p className="error">{error}</p>}
      <div className="grid-2">
        <section className="card">
          <h3>Agenda</h3>
          {events.length === 0 && <p className="muted">No events.</p>}
          <ul className="list">
            {events.map((e) => (
              <li key={e.id} className={e.is_focus_block ? "focus" : ""}>
                <span className="time">{fmtTime(e.start)}–{fmtTime(e.end)}</span>
                <div className="grow">
                  <div>{e.title}</div>
                  <small className="muted">{e.source}{e.location && ` · ${e.location}`}{e.attendees.length > 0 && ` · ${e.attendees.length} attendee(s)`}</small>
                </div>
                {e.source !== "google" && <button className="ghost icon" title="Delete" onClick={() => remove(e)}>✕</button>}
              </li>
            ))}
          </ul>
        </section>
        <div className="stack">
          <section className="card">
            <h3>Free time (30+ min)</h3>
            {slots.length === 0 && <p className="muted">No free slots in working hours.</p>}
            <ul className="list">
              {slots.map((s) => <li key={s.start}><span className="time">{fmtTime(s.start)}–{fmtTime(s.end)}</span><div>{Math.round((+new Date(s.end) - +new Date(s.start)) / 60000)} min</div></li>)}
            </ul>
          </section>
          <form className="card stack" onSubmit={create}>
            <h3>New event</h3>
            <input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required maxLength={300} />
            <div className="row">
              <label className="grow">Start<input type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} required /></label>
              <label className="grow">End<input type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} required /></label>
            </div>
            <input placeholder="Attendee emails, comma separated (invites are sent)" value={form.attendees} onChange={(e) => setForm({ ...form, attendees: e.target.value })} />
            <button className="primary">Add event</button>
          </form>
        </div>
      </div>
    </div>
  );
}
