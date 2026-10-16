import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { api, istTime, ROLE_LABEL } from "../api";
import { useAuth } from "../auth";
import { Empty } from "../components/ui";

const BLANK = { username: "", name: "", designation: "", police_station: "", role: "IO", password: "" };

export default function Officers() {
  const { t } = useT();
  const { me } = useAuth();
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const load = () => api.users().then(setUsers).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault(); setErr(""); setMsg("");
    try { await api.createUser(form); setMsg(t("Added {name}. They'll be asked to choose their own password at first sign-in.", { name: form.name })); setForm(BLANK); load(); }
    catch (x) { setErr(x.message); }
  };
  const patch = async (u, data) => { setErr(""); try { await api.updateUser(u.id, data); load(); } catch (x) { setErr(x.message); } };
  const reset = async (u) => {
    const pw = window.prompt(t("Temporary password for {name} (at least 8 characters, letters and numbers):", { name: u.name }));
    if (!pw) return;
    try { await api.resetPassword(u.id, pw); setMsg(t("Password reset for {name}. Give it to them in person; they must change it at sign-in.", { name: u.name })); }
    catch (x) { setErr(x.message); }
  };
  const f = (k) => ({ value: form[k], onChange: (e) => setForm({ ...form, [k]: e.target.value }) });

  return (
    <div>
      <div className="page-head">
        <h1>{t("Officers")}</h1>
        <p>{t("Who can sign in and what they can do. Changing a role or disabling an account signs that person out everywhere.")}</p>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <div className="note">{msg}</div>}
      <div className="two-col">
        <section className="panel">
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>{t("Officer")}</th><th>{t("Role")}</th><th>{t("Telegram")}</th><th>{t("Last sign-in")}</th><th /></tr></thead>
            <tbody>{users.map((u) => (
              <tr key={u.id} className={u.active ? "" : "muted"}>
                <td><b>{u.name}</b><div className="small muted">{u.username} · {u.designation}{u.police_station && ` · ${u.police_station}`}</div></td>
                <td><select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                  {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
                </select></td>
                <td className="small">{u.telegram_linked ? t("linked") : "—"}</td>
                <td className="small">{u.last_login ? istTime(u.last_login) : t("never")}</td>
                <td className="row-actions">
                  <button className="linkish" onClick={() => reset(u)}>{t("Reset password")}</button>
                  {u.id !== me.id && <button className="linkish" onClick={() => patch(u, { active: !u.active })}>{u.active ? t("Disable") : t("Enable")}</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
          {!users.length && <Empty title={t("No users")} />}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>{t("Add an officer")}</h2></div>
          <form className="stack-form" onSubmit={add}>
            <label>{t("Full name")}<input required {...f("name")} /></label>
            <label>{t("Username")}<input required {...f("username")} autoComplete="off" /></label>
            <label>{t("Designation")}<input {...f("designation")} placeholder={t("Sub-Inspector, Constable, Analyst…")} /></label>
            <label>{t("Police station / unit")}<input {...f("police_station")} /></label>
            <label>{t("Role")}<select {...f("role")}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}</select></label>
            <label>{t("Temporary password")}<input required type="password" {...f("password")} autoComplete="new-password" /></label>
            <button className="btn btn-primary">{t("Add officer")}</button>
          </form>
          <dl className="roles small">
            <dt>{t("Analyst")}</dt><dd>{t("Reviews cases and records verdicts. Phone and account numbers are partly hidden.")}</dd>
            <dt>{t("Investigating Officer")}</dt><dd>{t("Also moves cases through the workflow, sees complaint details, drafts notices and exports evidence.")}</dd>
            <dt>{t("Supervisor")}</dt><dd>{t("Also assigns cases, manages officers, reads the audit log and gets the daily brief.")}</dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
