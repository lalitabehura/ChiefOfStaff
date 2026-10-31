import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtTime, type Brief, type Integration } from "../api";

export default function Dashboard() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    api<Brief>("/agent/brief").then(setBrief).catch((e) => setError(e.message));
    api<Integration[]>("/integrations").then(setIntegrations).catch(() => {});
  };
  useEffect(load, []);

  async function connectDemo() {
    await api("/integrations/demo/connect", { method: "POST" });
    load();
  }

  if (error) return <p className="error">{error}</p>;
  if (!brief) return <p className="muted">Preparing your brief…</p>;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{new Date(brief.date + "T12:00").toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</p>
          <h1>Today</h1>
        </div>
      </header>

      {integrations && integrations.length === 0 && (
        <div className="card callout">
          <div>
            <strong>Connect your workspace</strong>
            <p className="muted">Link Google for real mail and calendar, or load a demo workspace to explore.</p>
          </div>
          <div className="row">
            <Link className="button" to="/settings">Connect Google</Link>
            <button className="primary" onClick={connectDemo}>Load demo data</button>
          </div>
        </div>
      )}

      <section className="card brief">
        <p className="brief-text">{brief.summary}</p>
        <div className="stats">
          <div><b>{brief.meeting_minutes}</b><span>min in meetings</span></div>
          <div><b>{brief.free_minutes}</b><span>min free</span></div>
          <div><b>{brief.overdue_count}</b><span>overdue</span></div>
          <div><b>{brief.pending_approvals}</b><span>awaiting you</span></div>
        </div>
        {brief.tips.map((t) => <p key={t} className="tip">💡 {t}</p>)}
      </section>

      <div className="grid-3">
        <section className="card">
          <h3>Top priorities <Link to="/tasks" className="more">All tasks →</Link></h3>
          {brief.top_tasks.length === 0 && <p className="muted">Nothing open. Enjoy it.</p>}
          <ol className="list">
            {brief.top_tasks.map((t) => (
              <li key={t.id}>
                <span className="score">{Math.round(t.priority_score)}</span>
                <div><div>{t.title}</div><small className="muted">{t.priority_reason}</small></div>
              </li>
            ))}
          </ol>
        </section>
        <section className="card">
          <h3>Schedule <Link to="/calendar" className="more">Calendar →</Link></h3>
          {brief.events.length === 0 && <p className="muted">No events today.</p>}
          <ul className="list">
            {brief.events.map((e) => (
              <li key={e.id} className={e.is_focus_block ? "focus" : ""}>
                <span className="time">{fmtTime(e.start)}</span>
                <div>{e.title}</div>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <h3>Needs a reply <Link to="/inbox" className="more">Inbox →</Link></h3>
          {brief.emails_needing_reply.length === 0 && <p className="muted">Inbox is under control.</p>}
          <ul className="list">
            {brief.emails_needing_reply.map((m) => (
              <li key={m.id}>
                <span className={`pill ${m.category}`}>{m.category}</span>
                <div><div>{m.subject}</div><small className="muted">{m.sender}</small></div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
