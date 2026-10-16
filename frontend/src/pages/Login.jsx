import { useEffect, useState } from "react";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  useEffect(() => { fetch("/api/health").then((r) => r.json()).then((d) => setDemo(!!d.demo_accounts)).catch(() => {}); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try { await login(u.trim(), p); } catch (x) { setErr(x.message); setBusy(false); }
  };

  return (
    <div className="login">
      <div className="login-side">
        <div className="brand"><img src="/favicon.svg" alt="" width="34" height="34" /><span>MuleWatch</span></div>
        <h1>Cyber crime command center</h1>
        <p>Finds online ads selling or renting bank accounts, ATM cards and banking kits, links them to victim
          complaints, and prepares the notices, bank requests and evidence to act on them.</p>
        <ul>
          <li>Every action is recorded in a tamper-evident audit log.</li>
          <li>Complaint data stays encrypted on this computer.</li>
          <li>Every flag is a lead for an officer to verify, never an automatic action.</li>
        </ul>
      </div>
      <form className="login-form" onSubmit={submit}>
        <h2>Sign in</h2>
        <label>Username<input value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" autoFocus required /></label>
        <label>Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required /></label>
        {err && <p className="err" role="alert">{err}</p>}
        <button className="btn btn-primary wide" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        {demo && <p className="muted small login-demo">Demo accounts: <code>analyst</code>, <code>io</code> (Investigating Officer) and <code>sho</code> (supervisor), password <code>mule@2026</code>.</p>}
      </form>
    </div>
  );
}
