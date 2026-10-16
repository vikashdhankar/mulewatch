import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, caseId, istTime } from "../api";
import { Empty, Icon } from "../components/ui";

const PAGE = 100;

export default function Audit() {
  const [sp, setSp] = useSearchParams();
  const [d, setD] = useState(null);
  const [chain, setChain] = useState(null);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const offset = Number(sp.get("offset") || 0);
  const set = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); if (k !== "offset") n.delete("offset"); setSp(n, { replace: true }); };

  useEffect(() => {
    api.audit({ user: sp.get("user"), action: sp.get("action"), case: sp.get("case"), limit: PAGE, offset })
      .then(setD).catch((e) => setErr(e.message));
  }, [sp]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.auditVerify().then(setChain); api.users().then(setUsers).catch(() => {}); }, []);

  if (err) return <Empty title="Audit log not available">{err}</Empty>;
  return (
    <div>
      <div className="page-head">
        <h1>Audit log</h1>
        <p>Every sign-in, case view, status change, complaint access, export and evidence capture. Each entry carries the hash of the one before it, so a changed or removed entry breaks the chain from that point.</p>
      </div>
      {chain && (
        <div className={`chain ${chain.ok ? "ok" : "bad"}`}>
          <Icon name={chain.ok ? "check" : "x"} />
          {chain.ok ? <span>Chain intact: {chain.rows} entries verified.</span>
            : <span>Chain broken at entry #{chain.broken_at}. The log was changed outside MuleWatch.</span>}
          <a className="btn" href="/api/audit.csv"><Icon name="download" /> Export CSV</a>
        </div>
      )}
      <div className="filters">
        <select value={sp.get("user") || ""} onChange={(e) => set("user", e.target.value)} aria-label="User">
          <option value="">Everyone</option>
          <option value="system">system</option>
          {users.map((u) => <option key={u.id} value={u.username}>{u.name} ({u.username})</option>)}
        </select>
        <select value={sp.get("action") || ""} onChange={(e) => set("action", e.target.value)} aria-label="Action">
          <option value="">All actions</option>
          {(d?.actions || []).map((a) => <option key={a}>{a}</option>)}
        </select>
        <form className="search" onSubmit={(e) => { e.preventDefault(); set("case", new FormData(e.target).get("c").replace(/\D/g, "").replace(/^0+/, "")); }}>
          <input name="c" defaultValue={sp.get("case") ? caseId(sp.get("case")) : ""} placeholder="Case, e.g. MW-00012" />
        </form>
      </div>
      <section className="panel">
        <div className="tbl-wrap"><table className="tbl tbl-tight audit">
          <thead><tr><th>#</th><th>When (IST)</th><th>Who</th><th>Action</th><th>Case</th><th>Detail</th><th>IP</th></tr></thead>
          <tbody>{(d?.items || []).map((r) => (
            <tr key={r.id}>
              <td className="muted small">{r.id}</td>
              <td className="small nowrap">{istTime(r.at)}</td>
              <td className="small"><b>{r.username}</b><div className="muted">{r.role}</div></td>
              <td><code>{r.action}</code></td>
              <td>{r.case_id && <Link to={`/case/${r.case_id}`}><code>{caseId(r.case_id)}</code></Link>}</td>
              <td className="small detail">{r.detail}</td>
              <td className="small muted">{r.ip}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {d && !d.items.length && <Empty title="No entries match" />}
        {d && d.total > PAGE && (
          <div className="pager">
            <button className="btn" disabled={offset === 0} onClick={() => set("offset", String(Math.max(0, offset - PAGE)))}>Newer</button>
            <span className="muted small">{offset + 1}–{Math.min(d.total, offset + PAGE)} of {d.total}</span>
            <button className="btn" disabled={offset + PAGE >= d.total} onClick={() => set("offset", String(offset + PAGE))}>Older</button>
          </div>
        )}
      </section>
    </div>
  );
}
