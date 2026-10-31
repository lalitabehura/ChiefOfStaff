import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import Agent from "./pages/Agent";
import Calendar from "./pages/Calendar";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import Login from "./pages/Login";
import ResetPassword from "./pages/ResetPassword";
import Rules from "./pages/Rules";
import Settings from "./pages/Settings";
import Tasks from "./pages/Tasks";

const NAV = [
  ["/", "Today"],
  ["/agent", "Assistant"],
  ["/tasks", "Tasks"],
  ["/calendar", "Calendar"],
  ["/inbox", "Inbox"],
  ["/rules", "Automations"],
  ["/settings", "Settings"],
] as const;

function Shell() {
  const { user, logout } = useAuth();
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const load = () => api<unknown[]>("/agent/actions?status=pending").then((a) => setPending(a.length)).catch(() => {});
    load();
    const id = setInterval(load, 30000);
    window.addEventListener("cos:actions-changed", load);
    return () => {
      clearInterval(id);
      window.removeEventListener("cos:actions-changed", load);
    };
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">✓</span>
          <div>
            <strong>Chief of Staff</strong>
            <small>{user?.full_name || user?.email}</small>
          </div>
        </div>
        <nav>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {label}
              {to === "/agent" && pending > 0 && <span className="badge">{pending}</span>}
            </NavLink>
          ))}
        </nav>
        <button className="ghost signout" onClick={logout}>Sign out</button>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agent" element={<Agent />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-screen">Loading…</div>;
  return (
    <Routes>
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/*" element={user ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
