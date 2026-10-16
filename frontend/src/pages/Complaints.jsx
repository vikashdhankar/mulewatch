import { useEffect, useState } from "react";
import { T, useT } from "../i18n";
import { Link } from "react-router-dom";
import { api, can, caseId, inr, istTime, STATUS } from "../api";
import { useAuth } from "../auth";
import { Empty, Icon, RiskBadge } from "../components/ui";
import { useLive } from "../live";

function Importer({ fields, onDone }) {
  const { t } = useT();
  const [up, setUp] = useState(null);
  const [mapping, setMapping] = useState({});
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  const choose = async (file) => {
    if (!file) return;
    setErr(""); setResult(null); setBusy(true);
    try {
      const d = await api.uploadComplaints(file);
      setUp(d); setMapping(d.mapping); setLabel(file.name.replace(/\.[^.]+$/, ""));
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const run = async () => {
    setBusy(true); setErr("");
    try { const r = await api.importComplaints(up.token, mapping, label); setResult(r); setUp(null); onDone(); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const mapped = Object.values(mapping).filter(Boolean);
  const hasIdent = mapped.some((f) => ["phone", "upi", "account", "ifsc", "url"].includes(f));

  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Import complaints")}</h2><a className="more" href="https://github.com/vikashdhankar/mulewatch/blob/main/docs/samples/sample_ncrp_complaints.csv" target="_blank" rel="noreferrer">{t("Sample file")}</a></div>
      {!up && (
        <>
          <p className="small">{t("Upload your unit's NCRP or 1930 complaint export (CSV or Excel). MuleWatch reads the suspect's mobile numbers, UPI IDs, bank accounts and links, and links any ad that uses the same identifiers.")} <b>{t("Victim names and contact details are never imported.")}</b> {t("The rest is stored encrypted on this computer.")}</p>
          <label className="file-drop">
            <input type="file" accept=".csv,.xlsx,.xlsm,text/csv" onChange={(e) => choose(e.target.files[0])} disabled={busy} />
            <Icon name="file" size={22} /><span>{busy ? t("Reading the file…") : t("Choose a CSV or .xlsx file")}</span>
          </label>
        </>
      )}
      {up && (
        <>
          <p className="small"><b>{up.filename}</b>: {t("{n} rows. Check which column is which. Columns left on “Don't import” are ignored.", { n: up.rows })}</p>
          <div className="map-tbl">
            <table className="tbl tbl-tight">
              <thead><tr><th>{t("Column in your file")}</th><th>{t("Example")}</th><th>{t("Use as")}</th></tr></thead>
              <tbody>{up.headers.map((h, i) => (
                <tr key={h}>
                  <td><b>{h}</b></td>
                  <td className="small muted ex">{up.preview.map((r) => r[i]).filter(Boolean).slice(0, 2).join(" · ") || "—"}</td>
                  <td><select value={mapping[h] || ""} onChange={(e) => setMapping({ ...mapping, [h]: e.target.value })}>
                    <option value="">{t("Don't import")}</option>
                    {Object.entries(fields).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
                  </select></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="import-row">
            <label>{t("Name this import")}<input value={label} onChange={(e) => setLabel(e.target.value)} /></label>
            <button className="btn" onClick={() => setUp(null)} disabled={busy}>{t("Cancel")}</button>
            <button className="btn btn-primary" onClick={run} disabled={busy || !hasIdent}>{busy ? t("Importing…") : t("Import {n} complaints", { n: up.rows })}</button>
          </div>
          {!hasIdent && <p className="err small">{t("Map at least one suspect identifier column (mobile, UPI, account, link or IFSC).")}</p>}
        </>
      )}
      {err && <p className="err small">{err}</p>}
      {result && <div className="note">{t("Imported {n} complaints.", { n: result.added })}{result.skipped ? " " + t("{n} skipped: already imported or no suspect identifier.", { n: result.skipped }) : ""} {t("{n} cases are now linked to complaints.", { n: result.cases_linked })}</div>}
    </section>
  );
}

export default function Complaints() {
  const { t } = useT();
  const { me } = useAuth();
  const { version } = useLive();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api.complaints().then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [version]);
  if (err) return <Empty title={t("Complaints aren't available")}>{err}</Empty>;
  if (!d) return <p className="muted">{t("Loading…")}</p>;
  const del = async (id, label) => {
    if (!window.confirm(t("Delete the import “{label}” and all its complaints? This can't be undone.", { label }))) return;
    await api.deleteImport(id); load();
  };
  return (
    <div>
      <div className="page-head">
        <h1>{t("Victim complaints")}</h1>
        <p>{t("An ad that uses the same phone number, UPI ID or account as a complaint is no longer just suspicious: it is tied to money already lost.")}</p>
      </div>
      <div className="kpis kpis-3">
        <div className="kpi"><strong>{d.total}</strong><span>{t("complaints imported")}</span></div>
        <div className="kpi crit"><strong>{d.matched}</strong><span>{t("matched to ads")}</span></div>
        <div className="kpi warn"><strong>{inr(d.matched_amount)}</strong><span>{t("lost in matched complaints")}</span></div>
      </div>
      <div className="two-col">
        <div>
          <section className="panel">
            <div className="panel-head"><h2>{t("Cases linked to complaints")}</h2><Link className="more" to="/cases?complaints=1">{t("All")}</Link></div>
            {d.cases.length ? (
              <div className="tbl-wrap"><table className="tbl">
                <thead><tr><th>{t("Case")}</th><th>{t("Risk")}</th><th>{t("Complaints")}</th><th>{t("Amount")}</th><th>{t("Status")}</th></tr></thead>
                <tbody>{d.cases.map((c) => (
                  <tr key={c.id}>
                    <td><Link to={`/case/${c.id}`}><code>{caseId(c.id)}</code></Link><div className="small muted">{t(c.category)} · {c.platform}</div></td>
                    <td><RiskBadge level={c.risk_level} score={c.risk_score} /></td>
                    <td>{c.complaints}</td><td>{inr(c.amount)}</td><td className="small">{t(STATUS[c.status])}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            ) : <p className="muted">{t("No ad matches an imported complaint yet.")}</p>}
          </section>
        </div>
        <div>
          <Importer fields={d.fields} onDone={load} />
          <section className="panel">
            <div className="panel-head"><h2>{t("Imports")}</h2></div>
            {d.imports.length ? d.imports.map((i) => (
              <div key={i.id} className="imp-row">
                <div><b>{i.label}</b><div className="small muted">{t("{n} complaints", { n: i.rows })} · {i.by} · {istTime(i.at)}{i.skipped ? ` · ${t("{n} skipped", { n: i.skipped })}` : ""}</div></div>
                {can(me, "SUPERVISOR") && <button className="icon-btn" title={t("Delete this import")} onClick={() => del(i.id, i.label)}><Icon name="x" size={16} /></button>}
              </div>
            )) : <p className="muted small">{t("Nothing imported yet.")}</p>}
            <p className="muted small"><T k="Complaint data is encrypted with the key in {path}. Back that folder up with the database." path={<code>backend/data/keys</code>} /></p>
          </section>
        </div>
      </div>
    </div>
  );
}
