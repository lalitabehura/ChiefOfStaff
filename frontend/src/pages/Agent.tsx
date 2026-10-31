import { useEffect, useRef, useState, type FormEvent } from "react";
import ActionCard from "../ActionCard";
import { api, notifyActionsChanged, type Action, type Message } from "../api";

const SUGGESTIONS = ["Plan my day", "What should I work on?", "Add task send invoice to Acme tomorrow", "Give me my brief"];

export default function Agent() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<Action[]>([]);
  const [history, setHistory] = useState<Action[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const loadActions = () => {
    api<Action[]>("/agent/actions?status=pending").then(setPending).catch(() => {});
    api<Action[]>("/agent/actions?status=all").then((a) => setHistory(a.filter((x) => x.status !== "pending").slice(0, 15))).catch(() => {});
  };

  useEffect(() => {
    api<Message[]>("/agent/messages").then(setMessages).catch(() => {});
    loadActions();
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function send(text: string) {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    const now = new Date().toISOString();
    setMessages((m) => [...m, { id: `local-${now}`, role: "user", content: text, created_at: now }]);
    setInput("");
    try {
      const r = await api<{ reply: string; actions: Action[] }>("/agent/chat", { method: "POST", body: { message: text } });
      setMessages((m) => [...m, { id: `reply-${now}`, role: "assistant", content: r.reply, created_at: new Date().toISOString() }]);
      loadActions();
      notifyActionsChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    await api("/agent/messages", { method: "DELETE" });
    setMessages([]);
  }

  return (
    <div className="page">
      <header className="page-head">
        <div><p className="eyebrow">Ask, delegate, approve</p><h1>Assistant</h1></div>
        {messages.length > 0 && <button className="ghost" onClick={clear}>Clear conversation</button>}
      </header>
      <div className="agent-layout">
        <section className="card chat">
          <div className="messages">
            {messages.length === 0 && (
              <div className="empty">
                <p>Tell me what you need. I'll propose actions — nothing leaves your account without your approval.</p>
                <div className="chips">{SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div>
              </div>
            )}
            {messages.map((m) => <div key={m.id} className={`bubble ${m.role}`}>{m.content}</div>)}
            {busy && <div className="bubble assistant typing">Thinking…</div>}
            <div ref={endRef} />
          </div>
          {error && <p className="error">{error}</p>}
          <form className="composer" onSubmit={(e: FormEvent) => { e.preventDefault(); send(input); }}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. Block 2 hours for the board report this week" maxLength={4000} disabled={busy} />
            <button className="primary" disabled={busy || !input.trim()}>Send</button>
          </form>
        </section>
        <section className="approvals">
          <h3>Waiting for approval {pending.length > 0 && <span className="badge">{pending.length}</span>}</h3>
          {pending.length === 0 && <p className="muted">Nothing pending.</p>}
          {pending.map((a) => <ActionCard key={a.id} action={a} onChange={loadActions} />)}
          {history.length > 0 && <h3 className="spaced">Recent</h3>}
          {history.map((a) => <ActionCard key={a.id} action={a} />)}
        </section>
      </div>
    </div>
  );
}
