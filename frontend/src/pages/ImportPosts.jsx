import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, can, caseId, istTime } from "../api";
import { useAuth } from "../auth";
import { useT } from "../i18n";
import { Empty, Icon, RiskBadge } from "../components/ui";

const LV = ["Critical", "High", "Medium", "Low"];
const RUNNING = ["running", "linking"];

function Upload({ onStarted }) {
  const { t } = useT();
  const [up, setUp] = useState(null);
  const [mapping, setMapping] = useState({});
  const [platform, setPlatform] = useState("");
  const [channel, setChannel] = useState("");
  const [label, setLabel] = useState("");
  const [push, setPush] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const choose = async (file) => {
    if (!file) return;
    setErr(""); setBusy(true);
    try {
      const d = await api.importUpload(file);
      setUp(d); setMapping(d.mapping); setPlatform(d.platform || ""); setChannel(d.channel || "");
      setLabel(file.name.replace(/\.[^.]+$/, ""));
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const start = async () => {
    setBusy(true); setErr("");
    try { const r = await api.importStart({ token: up.token, mapping, platform, channel, label, push }); onStarted(r.id); }
    catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const used = Object.values(mapping);
  const ok = used.includes("text") || used.includes("image");
  const hasChannel = used.includes("channel") || channel.trim();

  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Import a dataset")}</h2></div>
      {!up && (
        <>
          <p className="small">{t("Load posts exported from Telegram channels or other platforms. Every post is scored like a live one: cases, alerts, identifiers, seller rings and evidence hashes, with the post's original time and channel.")}</p>
          <label className="file-drop">
            <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.json,.jsonl,.ndjson,.zip" onChange={(e) => choose(e.target.files[0])} disabled={busy} />
            <Icon name="download" size={22} /><span>{busy ? t("Reading the file…") : t("Choose a CSV, Excel, JSON/JSONL file, a Telegram export (result.json) or a ZIP with images")}</span>
          </label>
          <p className="muted small">{t("A ZIP can hold the data file and its images; an image column may name a file in the ZIP or give a link. Up to 20,000 posts and 60 MB.")} {t("Times without a time zone are read as IST.")}</p>
        </>
      )}
      {up && (
        <>
          <p className="small"><b>{up.filename}</b> · {up.format} · {t("{n} posts", { n: up.rows })}
            {up.images > 0 && ` · ${t("{n} images", { n: up.images })}`}
            {up.truncated > 0 && <span className="err"> · {t("{n} more posts beyond the limit are left out", { n: up.truncated })}</span>}</p>
          <p className="small">{t("Check which column is which. Columns left on “Don't import” are ignored.")}</p>
          <div className="map-tbl">
            <table className="tbl tbl-tight">
              <thead><tr><th>{t("Column in your file")}</th><th>{t("Example")}</th><th>{t("Use as")}</th></tr></thead>
              <tbody>{up.columns.map((c, i) => (
                <tr key={c}>
                  <td><b>{c}</b></td>
                  <td className="small muted ex">{up.preview.map((r) => r[i]).filter(Boolean).slice(0, 2).join(" · ") || "—"}</td>
                  <td><select value={mapping[c] || ""} onChange={(e) => setMapping({ ...mapping, [c]: e.target.value })}>
                    <option value="">{t("Don't import")}</option>
                    {Object.entries(up.fields).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
                  </select></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="import-row">
            <label>{t("Platform")}<input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder={t("e.g. Telegram, Instagram")} /></label>
            {!used.includes("channel") && <label>{t("Channel / group")}<input value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="@channel" /></label>}
            <label>{t("Name this import")}<input value={label} onChange={(e) => setLabel(e.target.value)} /></label>
          </div>
          <label className="small check-row"><input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} /> {t("Also send Telegram alerts for critical posts (off: alerts show only in the command center)")}</label>
          <div className="import-row">
            <button className="btn" onClick={() => setUp(null)} disabled={busy}>{t("Cancel")}</button>
            <button className="btn btn-primary" onClick={start} disabled={busy || !ok}>{busy ? t("Starting…") : t("Import and score {n} posts", { n: up.rows })}</button>
          </div>
          {!ok && <p className="err small">{t("Choose the column that holds the post text.")}</p>}
          {ok && !hasChannel && <p className="muted small">{t("Tip: map or type the channel, so the dashboard shows where each post came from.")}</p>}
        </>
      )}
      {err && <p className="err small">{err}</p>}
    </section>
  );
}

function Job({ id }) {
  const { t } = useT();
  const { me } = useAuth();
  const [job, setJob] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let stop = false, tm;
    const load = () => api.importJob(id).then((j) => {
      if (stop) return;
      setJob(j);
      if (RUNNING.includes(j.status)) tm = setTimeout(load, 1500);
    }).catch((e) => setErr(e.message));
    load();
    return () => { stop = true; clearTimeout(tm); };
  }, [id]);
  if (err) return <Empty title={t("Import not found")}>{err}</Empty>;
  if (!job) return <p className="muted">{t("Loading…")}</p>;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  const status = { running: t("scoring…"), linking: t("linking repeated ads and shared identifiers…"), done: t("done"),
                   cancelled: t("stopped"), failed: t("failed") }[job.status];
  return (
    <section className="panel">
      <div className="panel-head"><h2>{job.label}</h2>
        {job.status === "running" && can(me, "IO") && <button className="btn" onClick={() => api.importCancel(id)}>{t("Stop")}</button>}</div>
      <p className="small muted">{job.filename} · {job.by} · {istTime(job.started)}</p>
      <div className="bulk-prog">
        <div className="bar"><i style={{ width: `${pct}%` }} /></div>
        <span className="small">{t("{a} of {b} posts", { a: job.done, b: job.total })} · {status}</span>
      </div>
      <div className="bulk-levels">
        {LV.filter((l) => job.levels[l]).map((l) => <span key={l} className={`risk risk-${l.toLowerCase()}`}><b>{job.levels[l]}</b>{t(l)}</span>)}
        {job.duplicates > 0 && <span className="chip">{t("{n} already imported", { n: job.duplicates })}</span>}
        {job.empty > 0 && <span className="chip">{t("{n} empty", { n: job.empty })}</span>}
        {job.images > 0 && <span className="chip">{t("{n} with images", { n: job.images })}</span>}
        {job.errors > 0 && <span className="chip">{t("{n} couldn't be read", { n: job.errors })}</span>}
      </div>
      {job.error && <p className="err small">{job.error}</p>}
      {job.top?.length > 0 && (
        <>
          <h3 className="small">{t("Highest risk in this import")}</h3>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>{t("Case")}</th><th>{t("Risk")}</th><th>{t("Post")}</th><th>{t("Posted")}</th></tr></thead>
            <tbody>{job.top.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/case/${p.id}`}><code>{caseId(p.id)}</code></Link><div className="small muted">{t(p.category)}</div></td>
                <td><RiskBadge level={p.risk_level} score={p.risk_score} />{p.cluster_size > 1 && <div className="small muted">{t("ring of {n}", { n: p.cluster_size })}</div>}</td>
                <td className="small">{p.excerpt}<div className="muted">{p.platform}{p.author && p.author !== p.platform ? ` · ${p.author}` : ""}</div></td>
                <td className="small">{p.posted_at ? istTime(p.posted_at) : "—"}</td>
              </tr>
            ))}</tbody>
          </table></div>
          {job.status === "done" && <p className="small"><Link to="/cases">{t("Open all cases")}</Link> · <Link to="/network">{t("Seller network")}</Link></p>}
        </>
      )}
    </section>
  );
}

export default function ImportPosts() {
  const { t } = useT();
  const { id } = useParams();
  const nav = useNavigate();
  const [jobs, setJobs] = useState([]);
  useEffect(() => { api.importJobs().then(setJobs).catch(() => {}); }, [id]);
  return (
    <div>
      <div className="page-head">
        <h1>{t("Import dataset")}</h1>
        <p>{t("Posts collected elsewhere (a Telegram channel export, a provided sample dataset, a spreadsheet of social-media posts) go through the same detection as live monitoring.")}</p>
      </div>
      <div className="two-col">
        <div>{id ? <Job id={Number(id)} /> : <Upload onStarted={(jid) => nav(`/import/${jid}`)} />}</div>
        <div>
          {id && <p><Link className="btn" to="/import">{t("Import another file")}</Link></p>}
          <section className="panel">
            <div className="panel-head"><h2>{t("Imports")}</h2></div>
            {jobs.length ? jobs.map((j) => (
              <div key={j.id} className="imp-row">
                <div><Link to={`/import/${j.id}`}><b>{j.label}</b></Link>
                  <div className="small muted">{t("{n} new posts", { n: j.added })} · {j.by} · {istTime(j.started)}{RUNNING.includes(j.status) ? ` · ${t("running")}` : ""}</div></div>
              </div>
            )) : <p className="muted small">{t("Nothing imported since the command center started.")}</p>}
          </section>
        </div>
      </div>
    </div>
  );
}
