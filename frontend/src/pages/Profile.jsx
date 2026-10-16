import { useState } from "react";
import { api, ROLE_LABEL } from "../api";
import { useAuth } from "../auth";

export default function Profile() {
  const { me, refresh } = useAuth();
  const [old, setOld] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [code, setCode] = useState(null);

  const change = async (e) => {
    e.preventDefault(); setErr(""); setMsg("");
    if (pw !== pw2) { setErr("The new passwords don't match"); return; }
    try { await api.changePassword(old, pw); setMsg("Password changed."); setOld(""); setPw(""); setPw2(""); refresh(); }
    catch (x) { setErr(x.message); }
  };

  return (
    <div>
      <div className="page-head">
        <h1>My account</h1>
        <p>{me.name} · {me.designation} · {ROLE_LABEL[me.role]}{me.police_station && ` · ${me.police_station}`}</p>
      </div>
      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>Password</h2></div>
          {me.must_change_password && <p className="err small">Choose your own password to continue.</p>}
          <form className="stack-form" onSubmit={change}>
            <label>Current password<input type="password" value={old} onChange={(e) => setOld(e.target.value)} required autoComplete="current-password" /></label>
            <label>New password<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required autoComplete="new-password" /></label>
            <label>Repeat new password<input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required autoComplete="new-password" /></label>
            <button className="btn btn-primary">Change password</button>
          </form>
          {err && <p className="err small">{err}</p>}
          {msg && <p className="ok-text small">{msg}</p>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Telegram</h2><span className={`chip ${me.telegram_linked ? "chip-ok" : ""}`}>{me.telegram_linked ? "linked" : "not linked"}</span></div>
          <p className="small">Get alerts for cases assigned to you on your phone{me.role === "SUPERVISOR" ? ", plus the daily brief every morning" : ""}.</p>
          {code ? (
            <p>Send <code className="code-big">/officer {code.code}</code> to {code.bot ? <a href={`https://t.me/${code.bot}`} target="_blank" rel="noreferrer">@{code.bot}</a> : "the MuleWatch bot"} from your Telegram. <button className="linkish" onClick={refresh}>I've sent it</button></p>
          ) : (
            <button className="btn" onClick={async () => setCode(await api.telegramCode())}>{me.telegram_linked ? "Link a different Telegram" : "Link Telegram"}</button>
          )}
          {me.telegram_linked && <p><button className="linkish" onClick={async () => { await api.telegramUnlink(); refresh(); }}>Unlink Telegram</button></p>}
        </section>
      </div>
    </div>
  );
}
