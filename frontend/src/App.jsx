import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, can, caseId, ROLE_LABEL, timeAgo } from "./api";
import { useAuth } from "./auth";
import { LangSwitch, T, useT } from "./i18n";
import Bulk from "./pages/Bulk";
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
  ["/bulk", "Bulk link check", "list", "ANALYST"],
  ["/watchlist", "Watchlist", "eye", "ANALYST"],
  ["/sources", "Monitored sources", "globe", "ANALYST"],
  ["/brief", "Daily brief", "doc", "SUPERVISOR"],
  ["/officers", "Officers", "users", "SUPERVISOR"],
  ["/audit", "Audit log", "lock", "SUPERVISOR"],
];

function MonitorStatus() {
  const { connected, version } = useLive();
  const { t } = useT();
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
        {connected ? (err ? t("Source unreachable") : oldForum ? t("Comments not readable: update the forum") : t(active.length === 1 ? "Monitoring {n} source" : "Monitoring {n} sources", { n: active.length })) : t("Reconnecting…")}
        {last && <small>{t("last crawl {ago}", { ago: timeAgo(last) })}</small>}
      </span>
    </Link>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  const { t } = useT();
  return (
    <div className="toasts" aria-live="assertive">
      {toasts.map((a) => (
        <div key={a.id} className={`toast toast-${a.level.toLowerCase()}`}>
          <div className="toast-head">
            <strong>{t("{level} alert", { level: t(a.level) })}</strong>
            {a.post && <span>{caseId(a.post.id)} · {a.post.platform}</span>}
            <button onClick={() => dismiss(a.id)} aria-label={t("Dismiss")}><Icon name="x" size={16} /></button>
          </div>
          {a.post && <p className="toast-text">{a.post.excerpt}</p>}
          <p className="toast-why">{a.reason}</p>
          {a.post && <Link to={`/case/${a.post.id}`} onClick={() => dismiss(a.id)} className="toast-open">{t("Open case")}</Link>}
        </div>
      ))}
    </div>
  );
}

function UserMenu() {
  const { me, logout } = useAuth();
  const { t } = useT();
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
        <span className="user-txt"><b>{me.name || me.username}</b><small>{t(ROLE_LABEL[me.role])}</small></span>
      </button>
      {open && (
        <div className="user-pop" role="menu">
          <div className="user-pop-head"><b>{me.name}</b><span>{me.designation}{me.police_station && ` · ${me.police_station}`}</span></div>
          <Link to="/profile" onClick={() => setOpen(false)}><Icon name="user" size={16} /> {t("My account and Telegram")}</Link>
          <button onClick={logout}><Icon name="logout" size={16} /> {t("Sign out")}</button>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const { soundOn, enableSound } = useLive();
  const { me } = useAuth();
  const { t } = useT();
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
              <Icon name={icon} /> {t(label)}
            </NavLink>
          ))}
        </nav>
        <div className="side-foot">
          {t("Detecting sale and rental of bank accounts, ATM cards and banking kits on public platforms.")}
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <button className="menu-btn" onClick={() => setMenu(!menu)} aria-label={t("Menu")}>☰</button>
          <MonitorStatus />
          <div className="top-right">
            <LangSwitch />
            <button className={`sound${soundOn ? " on" : ""}`} onClick={enableSound} title={t("Alert sound")}>
              <Icon name={soundOn ? "sound" : "mute"} /> <span>{soundOn ? t("Sound on") : t("Sound off")}</span>
            </button>
            <UserMenu />
          </div>
        </header>
        {me.must_change_password && loc.pathname !== "/profile" && (
          <div className="banner warn"><T k="Your password was set by a supervisor. {link} before you continue." link={<Link to="/profile">{t("Choose your own password")}</Link>} /></div>
        )}
        {me.demo_accounts_active && (
          <div className="banner">{t("Demo accounts with the shared password are still active. Disable them or change their passwords on the Officers page before real use.")} <Link to="/officers">{t("Officers")}</Link></div>
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
            <Route path="/bulk" element={<Bulk />} />
            <Route path="/bulk/:id" element={<Bulk />} />
            <Route path="*" element={<p>{t("Page not found.")} <Link to="/">{t("Back to the command center")}</Link></p>} />
          </Routes>
        </main>
      </div>
      <Toasts />
    </div>
  );
}

export { RiskBadge };
