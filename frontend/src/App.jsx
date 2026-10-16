import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, can, caseId, ROLE_LABEL, timeAgo } from "./api";
import { useAuth } from "./auth";
import { Icon, RiskBadge } from "./components/ui";
import { useLive } from "./live";
import Analyze from "./pages/Analyze";
import Audit from "./pages/Audit";
import Brief from "./pages/Brief";
import CaseDetail from "./pages/CaseDetail";
import Cases from "./pages/Cases";
import Complaints from "./pages/Complaints";
import Dashboard from "./pages/Dashboard";
import MapPage from "./pages/MapPage";
import Network from "./pages/Network";
import Officers from "./pages/Officers";
import Profile from "./pages/Profile";
import Sources from "./pages/Sources";
import Watchlist from "./pages/Watchlist";

// [path, label, icon, minimum role]
const NAV = [
  ["/", "Command center", "radar", "ANALYST"],
  ["/cases", "Cases", "cases", "ANALYST"],
  ["/network", "Seller network", "graph", "ANALYST"],
  ["/map", "District map", "map", "ANALYST"],
  ["/complaints", "Victim complaints", "file", "IO"],
  ["/analyze", "Check a post", "scan", "ANALYST"],
  ["/watchlist", "Watchlist", "eye", "ANALYST"],
  ["/sources", "Monitored sources", "globe", "ANALYST"],
  ["/brief", "Daily brief", "doc", "SUPERVISOR"],
  ["/officers", "Officers", "users", "SUPERVISOR"],
  ["/audit", "Audit log", "lock", "SUPERVISOR"],
];

function MonitorStatus() {
  const { connected, version } = useLive();
  const [src, setSrc] = useState(null);
  useEffect(() => {
    const load = () => api.sources().then(setSrc).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [version]);
  const active = src?.sources?.filter((s) => s.enabled) || [];
  const err = active.some((s) => s.last_status?.startsWith("error"));
  const last = active.map((s) => s.last_crawl).filter(Boolean).sort().pop();
  const oldForum = active.some((s) => s.last_status?.includes("update the forum"));
  return (
    <Link to="/sources" className={`monitor ${connected && !err && !oldForum ? "on" : "off"}`}>
      <span className="pulse" />
      <span>
        {connected ? (err ? "Source unreachable" : oldForum ? "Comments not readable: update the forum" : `Monitoring ${active.length} source${active.length === 1 ? "" : "s"}`) : "Reconnecting…"}
        {last && <small>last crawl {timeAgo(last)}</small>}
      </span>
    </Link>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.level.toLowerCase()}`}>
          <div className="toast-head">
            <strong>{t.level} alert</strong>
            {t.post && <span>{caseId(t.post.id)} · {t.post.platform}</span>}
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss"><Icon name="x" size={16} /></button>
          </div>
          {t.post && <p className="toast-text">{t.post.excerpt}</p>}
          <p className="toast-why">{t.reason}</p>
          {t.post && <Link to={`/case/${t.post.id}`} onClick={() => dismiss(t.id)} className="toast-open">Open case</Link>}
        </div>
      ))}
    </div>
  );
}

function UserMenu() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const initials = (me.name || me.username).split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="user-menu" ref={ref}>
      <button className="user-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="avatar">{initials}</span>
        <span className="user-txt"><b>{me.name || me.username}</b><small>{ROLE_LABEL[me.role]}</small></span>
      </button>
      {open && (
        <div className="user-pop" role="menu">
          <div className="user-pop-head"><b>{me.name}</b><span>{me.designation}{me.police_station && ` · ${me.police_station}`}</span></div>
          <Link to="/profile" onClick={() => setOpen(false)}><Icon name="user" size={16} /> My account and Telegram</Link>
          <button onClick={logout}><Icon name="logout" size={16} /> Sign out</button>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const { soundOn, enableSound } = useLive();
  const { me } = useAuth();
  const loc = useLocation();
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [loc.pathname]);

  return (
    <div className="shell">
      <aside className={`side${menu ? " open" : ""}`}>
        <Link to="/" className="brand">
          <img src="/favicon.svg" alt="" width="30" height="30" />
          <span>MuleWatch</span>
        </Link>
        <nav>
          {NAV.filter((n) => can(me, n[3])).map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/"} className="nav">
              <Icon name={icon} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          Detecting sale and rental of bank accounts, ATM cards and banking kits on public platforms.
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setMenu(!menu)} aria-label="Menu">☰</button>
          <MonitorStatus />
          <div className="top-right">
            <button className={`sound${soundOn ? " on" : ""}`} onClick={enableSound} title="Alert sound">
              <Icon name={soundOn ? "sound" : "mute"} /> <span>{soundOn ? "Sound on" : "Sound off"}</span>
            </button>
            <UserMenu />
          </div>
        </header>
        {me.must_change_password && loc.pathname !== "/profile" && (
          <div className="banner warn">Your password was set by a supervisor. <Link to="/profile">Choose your own password</Link> before you continue.</div>
        )}
        {me.demo_accounts_active && (
          <div className="banner">Demo accounts with the shared password are still active. Disable them or change their passwords on the <Link to="/officers">Officers</Link> page before real use.</div>
        )}
        <main className="page">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cases" element={<Cases />} />
            <Route path="/case/:id" element={<CaseDetail />} />
            <Route path="/network" element={<Network />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/complaints" element={<Complaints />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/brief" element={<Brief />} />
            <Route path="/officers" element={<Officers />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="*" element={<p>Page not found. <Link to="/">Back to the command center</Link></p>} />
          </Routes>
        </main>
      </div>
      <Toasts />
    </div>
  );
}

export { RiskBadge };
