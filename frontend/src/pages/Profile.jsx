import { useState } from "react";
import { T, useT } from "../i18n";
import { api, ROLE_LABEL } from "../api";
import { useAuth } from "../auth";

export default function Profile() {
  const { t } = useT();
  const { me, refresh } = useAuth();
  const [old, setOld] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [code, setCode] = useState(null);

  const change = async (e) => {
    e.preventDefault(); setErr(""); setMsg("");
    if (pw !== pw2) { setErr(t("The new passwords don't match")); return; }
    try { await api.changePassword(old, pw); setMsg(t("Password changed.")); setOld(""); setPw(""); setPw2(""); refresh(); }
    catch (x) { setErr(x.message); }
  };

  return (
    <div>
      <div className="page-head">
        <h1>{t("My account")}</h1>
        <p>{me.name} · {me.designation} · {t(ROLE_LABEL[me.role])}{me.police_station && ` · ${me.police_station}`}</p>
      </div>
      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>{t("Password")}</h2></div>
          {me.must_change_password && <p className="err small">{t("Choose your own password to continue.")}</p>}
          <form className="stack-form" onSubmit={change}>
            <label>{t("Current password")}<input type="password" value={old} onChange={(e) => setOld(e.target.value)} required autoComplete="current-password" /></label>
            <label>{t("New password")}<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required autoComplete="new-password" /></label>
            <label>{t("Repeat new password")}<input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} required autoComplete="new-password" /></label>
            <button className="btn btn-primary">{t("Change password")}</button>
          </form>
          {err && <p className="err small">{err}</p>}
          {msg && <p className="ok-text small">{msg}</p>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>{t("Telegram")}</h2><span className={`chip ${me.telegram_linked ? "chip-ok" : ""}`}>{me.telegram_linked ? t("linked") : t("not linked")}</span></div>
          <p className="small">{me.role === "SUPERVISOR" ? t("Get alerts for cases assigned to you on your phone, plus the daily brief every morning.") : t("Get alerts for cases assigned to you on your phone.")}</p>
          {code ? (
            <p><T k="Send {cmd} to {bot} from your Telegram." cmd={<code className="code-big">/officer {code.code}</code>} bot={code.bot ? <a href={`https://t.me/${code.bot}`} target="_blank" rel="noreferrer">@{code.bot}</a> : t("the MuleWatch bot")} /> <button className="linkish" onClick={refresh}>{t("I've sent it")}</button></p>
          ) : (
            <button className="btn" onClick={async () => setCode(await api.telegramCode())}>{me.telegram_linked ? t("Link a different Telegram") : t("Link Telegram")}</button>
          )}
          {me.telegram_linked && <p><button className="linkish" onClick={async () => { await api.telegramUnlink(); refresh(); }}>{t("Unlink Telegram")}</button></p>}
        </section>
      </div>
    </div>
  );
}
