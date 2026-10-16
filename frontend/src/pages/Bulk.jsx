import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, caseId, istTime } from "../api";
import { useT } from "../i18n";
import { Empty, Icon, RiskBadge } from "../components/ui";

const LV = ["Critical", "High", "Medium", "Low"];

function Progress({ job }) {
  const { t } = useT();
  const pct = job.total ? Math.round((job.checked / job.total) * 100) : 0;
  return (
    <div className="bulk-prog">
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
      <span className="small">{t("{a} of {b} checked", { a: job.checked, b: job.total })}
        {job.status === "running" && ` · ${t("checking…")}`}{job.status === "cancelled" && ` · ${t("stopped")}`}</span>
    </div>
  );
}

function Levels({ job }) {
  const { t } = useT();
  return (
    <div className="bulk-levels">
      {LV.filter((l) => job.levels[l]).map((l) => <span key={l} className={`risk risk-${l.toLowerCase()}`}><b>{job.levels[l]}</b>{t(l)}</span>)}
      {job.counts.error > 0 && <span className="chip">{t("{n} couldn't be opened", { n: job.counts.error })}</span>}
      {job.counts.existing > 0 && <span className="chip">{t("{n} already cases", { n: job.counts.existing })}</span>}
    </div>
  );
}

function NewList({ onCreated }) {
  const { t } = useT();
  const [text, setText] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const count = (text.match(/(?:https?:\/\/|www\.|\bt\.me\/|\bwa\.me\/)\S+/gi) || []).length;
  const go = async (fn) => {
    setBusy(true); setErr("");
    try { const r = await fn(); onCreated(r.id); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("New list")}</h2></div>
      <p className="small">{t("Paste the links you collected, one per line. Anything else on the same line (a complaint number, where you found it) is kept as a note.")}</p>
      <textarea className="bulk-text" rows={9} value={text} onChange={(e) => setText(e.target.value)}
        placeholder={"https://t.me/somechannel/123   from complaint 31209260002\nhttps://www.olx.in/item/…\nhttps://www.facebook.com/groups/…/posts/…"} />
      <div className="import-row">
        <label>{t("Name this list")}<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("e.g. Links from Jhotwara patrol, 17 Oct")} /></label>
        <button className="btn btn-primary" disabled={busy || !count} onClick={() => go(() => api.bulkCreate(text, label))}>
          {count ? t("Check {n} links", { n: count }) : t("Check links")}</button>
      </div>
      <div className="or-line"><span>{t("or")}</span></div>
      <label className="file-drop">
        <input type="file" accept=".txt,.csv,.xlsx,.xlsm,text/plain,text/csv" disabled={busy}
          onChange={(e) => e.target.files[0] && go(() => api.bulkUpload(e.target.files[0], label))} />
        <Icon name="file" size={22} /><span>{t("Upload a .txt, .csv or Excel file with links")}</span>
      </label>
      {err && <p className="err small">{err}</p>}
      <p className="muted small">{t("Links are opened one at a time with a short pause, the same way as Check a post. Up to 500 links per list. Telegram gets one summary when the list is done.")}</p>
    </section>
  );
}

function JobDetail({ id }) {
  const { t } = useT();
  const [job, setJob] = useState(null);
  const [err, setErr] = useState("");
  const [show, setShow] = useState("flagged");
  useEffect(() => {
    let stop = false;
    const load = () => api.bulkJob(id).then((j) => { if (!stop) setJob(j); }).catch((e) => setErr(e.message));
    load();
    const tm = setInterval(load, 2500);
    return () => { stop = true; clearInterval(tm); };
  }, [id]);
  if (err) return <Empty title={t("List not found")}>{err}</Empty>;
  if (!job) return <p className="muted">{t("Loading…")}</p>;
  const items = job.items.filter((i) => show === "all" ? true : show === "errors" ? i.status === "error"
    : i.post && ["Critical", "High"].includes(i.post.risk_level));
  return (
    <div>
      <Link to="/bulk" className="back">{t("All lists")}</Link>
      <div className="page-head">
        <h1>{job.label}</h1>
        <p>{t("Started by {who} · {when} IST", { who: job.by, when: istTime(job.created_at) })}</p>
      </div>
      <section className="panel">
        <Progress job={job} />
        <Levels job={job} />
        {["queued", "running"].includes(job.status) && <button className="btn" onClick={() => api.bulkCancel(id)}>{t("Stop this list")}</button>}
      </section>
      <div className="filters">
        <div className="seg">
          {[["flagged", t("High and Critical")], ["all", t("All links")], ["errors", t("Couldn't open")]].map(([k, l]) => (
            <button key={k} className={`seg-btn${show === k ? " on-indigo" : ""}`} onClick={() => setShow(k)}>{l}</button>
          ))}
        </div>
      </div>
      <section className="panel">
        {items.length ? (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>{t("Link")}</th><th>{t("Result")}</th><th>{t("Case")}</th></tr></thead>
            <tbody>{items.map((i) => (
              <tr key={i.id}>
                <td className="bulk-url"><a href={i.url} target="_blank" rel="noreferrer noopener">{i.url}</a>
                  {i.note && <div className="small muted">{i.note}</div>}
                  {i.post?.excerpt && <div className="small">{i.post.excerpt}</div>}</td>
                <td>{i.post ? <RiskBadge level={i.post.risk_level} score={i.post.risk_score} />
                  : i.status === "error" ? <span className="small err">{i.error}</span>
                  : <span className="chip">{t(i.status === "queued" ? "waiting" : i.status)}</span>}
                  {i.post?.complaint_count > 0 && <div><span className="chip chip-comp">{t("{n} complaints", { n: i.post.complaint_count })}</span></div>}
                  {i.status === "existing" && <div className="small muted">{t("already a case")}</div>}</td>
                <td>{i.post && <Link to={`/case/${i.post.id}`}><code>{caseId(i.post.id)}</code></Link>}
                  {i.post && <div className="small muted">{t(i.post.category)}</div>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty title={show === "flagged" ? t("Nothing High or Critical yet") : t("No links here")} />}
      </section>
    </div>
  );
}

export default function Bulk() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useT();
  const [jobs, setJobs] = useState([]);
  useEffect(() => {
    if (id) return undefined;
    const load = () => api.bulkJobs().then(setJobs).catch(() => {});
    load();
    const tm = setInterval(load, 3000);
    return () => clearInterval(tm);
  }, [id]);
  if (id) return <JobDetail id={id} />;
  return (
    <div>
      <div className="page-head">
        <h1>{t("Bulk link check")}</h1>
        <p>{t("Check many links at once: links from complaints, patrolling, tips or other units. Each one is fetched and scored like a single post, and flagged ones become cases.")}</p>
      </div>
      <div className="two-col">
        <NewList onCreated={(jid) => nav(`/bulk/${jid}`)} />
        <section className="panel">
          <div className="panel-head"><h2>{t("Lists")}</h2></div>
          {jobs.length ? jobs.map((j) => (
            <Link key={j.id} to={`/bulk/${j.id}`} className="bulk-job">
              <div className="bulk-job-head"><b>{j.label}</b><span className="small muted">{j.by} · {istTime(j.created_at)}</span></div>
              <Progress job={j} />
              <Levels job={j} />
            </Link>
          )) : <p className="muted small">{t("No lists yet.")}</p>}
        </section>
      </div>
    </div>
  );
}
