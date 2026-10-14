import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { LookupsProvider } from "./lookups";
import ClientDetail from "./pages/ClientDetail";
import Clients from "./pages/Clients";
import ComingSoon from "./pages/ComingSoon";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import Settings from "./pages/Settings";
import Tasks from "./pages/Tasks";

const NAV = [
  { to: "/tasks", label: "משימות" },
  { to: "/clients", label: "לקוחות" },
  { to: "/projects", label: "פרויקטים" },
  { to: "/finance", label: "כספים", soon: true },
  { to: "/mail", label: "מיילים", soon: true },
  { to: "/whatsapp", label: "וואטסאפ", soon: true },
  { to: "/vault", label: "כספת", soon: true },
  { to: "/settings", label: "הגדרות" },
];

export default function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    api<{ phone: string }>("/auth/me")
      .then((me) => setUser(me.phone))
      .catch(() => setUser(null));
    const onUnauthorized = () => setUser(null);
    window.addEventListener("unauthorized", onUnauthorized);
    return () => window.removeEventListener("unauthorized", onUnauthorized);
  }, []);

  if (user === undefined) return <div className="center muted">טוען…</div>;
  if (user === null) return <Login onLogin={setUser} />;

  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setUser(null);
  };

  return (
    <LookupsProvider>
      <div className="layout">
        <header className="topbar">
          <button className="icon-btn menu-toggle" onClick={() => setMenuOpen(!menuOpen)} aria-label="תפריט">
            ☰
          </button>
          <span className="brand">העוזר שלי</span>
          <button className="link-btn" onClick={logout}>
            יציאה
          </button>
        </header>
        <nav className={`sidebar ${menuOpen ? "open" : ""}`} onClick={() => setMenuOpen(false)}>
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
              {item.label}
              {item.soon && <span className="badge">בקרוב</span>}
            </NavLink>
          ))}
        </nav>
        <main className="content">
          <Routes>
            <Route path="/" element={<Navigate to="/tasks" replace />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/clients" element={<Clients />} />
            <Route path="/clients/:id" element={<ClientDetail />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/settings" element={<Settings />} />
            {NAV.filter((n) => n.soon).map((n) => (
              <Route key={n.to} path={n.to} element={<ComingSoon title={n.label} />} />
            ))}
            <Route path="*" element={<Navigate to="/tasks" replace />} />
          </Routes>
        </main>
      </div>
    </LookupsProvider>
  );
}
