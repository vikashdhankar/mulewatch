import { useEffect, useState } from "react";
import { api, istTime, ROLE_LABEL } from "../api";
import { useAuth } from "../auth";
import { Empty } from "../components/ui";

const BLANK = { username: "", name: "", designation: "", police_station: "", role: "IO", password: "" };

export default function Officers() {
  const { me } = useAuth();
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const load = () => api.users().then(setUsers).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault(); setErr(""); setMsg("");
    try { await api.createUser(form); setMsg(`Added ${form.name}. They'll be asked to choose their own password at first sign-in.`); setForm(BLANK); load(); }
    catch (x) { setErr(x.message); }
  };
  const patch = async (u, data) => { setErr(""); try { await api.updateUser(u.id, data); load(); } catch (x) { setErr(x.message); } };
  const reset = async (u) => {
    const pw = window.prompt(`Temporary password for ${u.name} (at least 8 characters, letters and numbers):`);
    if (!pw) return;
    try { await api.resetPassword(u.id, pw); setMsg(`Password reset for ${u.name}. Give it to them in person; they must change it at sign-in.`); }
    catch (x) { setErr(x.message); }
  };
  const f = (k) => ({ value: form[k], onChange: (e) => setForm({ ...form, [k]: e.target.value }) });

  return (
    <div>
      <div className="page-head">
        <h1>Officers</h1>
        <p>Who can sign in and what they can do. Changing a role or disabling an account signs that person out everywhere.</p>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <div className="note">{msg}</div>}
      <div className="two-col">
        <section className="panel">
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Officer</th><th>Role</th><th>Telegram</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>{users.map((u) => (
              <tr key={u.id} className={u.active ? "" : "muted"}>
                <td><b>{u.name}</b><div className="small muted">{u.username} · {u.designation}{u.police_station && ` · ${u.police_station}`}</div></td>
                <td><select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                  {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select></td>
                <td className="small">{u.telegram_linked ? "linked" : "—"}</td>
                <td className="small">{u.last_login ? istTime(u.last_login) : "never"}</td>
                <td className="row-actions">
                  <button className="linkish" onClick={() => reset(u)}>Reset password</button>
                  {u.id !== me.id && <button className="linkish" onClick={() => patch(u, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
          {!users.length && <Empty title="No users" />}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Add an officer</h2></div>
          <form className="stack-form" onSubmit={add}>
            <label>Full name<input required {...f("name")} /></label>
            <label>Username<input required {...f("username")} autoComplete="off" /></label>
            <label>Designation<input {...f("designation")} placeholder="Sub-Inspector, Constable, Analyst…" /></label>
            <label>Police station / unit<input {...f("police_station")} /></label>
            <label>Role<select {...f("role")}>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Temporary password<input required type="password" {...f("password")} autoComplete="new-password" /></label>
            <button className="btn btn-primary">Add officer</button>
          </form>
          <dl className="roles small">
            <dt>Analyst</dt><dd>Reviews cases and records verdicts. Phone and account numbers are partly hidden.</dd>
            <dt>Investigating Officer</dt><dd>Also moves cases through the workflow, sees complaint details, drafts notices and exports evidence.</dd>
            <dt>Supervisor</dt><dd>Also assigns cases, manages officers, reads the audit log and gets the daily brief.</dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
