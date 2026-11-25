import { BarController, BarElement, CategoryScale, Chart, Legend, LinearScale, LineController, LineElement, PointElement, Tooltip } from "chart.js";
import { useEffect, useState } from "react";
import { Bar } from "react-chartjs-2";
import { Link } from "react-router-dom";
import { api, can, caseId, istTime, timeAgo } from "../api";
import { useAuth } from "../auth";
import { DecisionButtons, Empty, Icon, RiskBadge } from "../components/ui";
import { tr, useT } from "../i18n";
import { useLive } from "../live";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, LineController, LineElement, PointElement, Tooltip, Legend);

const CATS = ["payout_mule", "account_sale", "usdt_p2p", "crypto_investment_scam", "task_job_scam"];
const CAT_LABEL = { payout_mule: "Payout Mule", account_sale: "Account Sale", usdt_p2p: "USDT P2P",
  crypto_investment_scam: "Crypto Investment Scam", task_job_scam: "Task/Job Scam", legit_finance: "Legit Finance", unrelated: "Unrelated" };
const KIND = { PHONE: "Phone", UPI: "UPI ID", ACCOUNT: "Account no.", CARD: "Card no.", HANDLE: "Handle" };
const secs = (s) => (s == null ? "–" : s < 90 ? tr("{n} s", { n: s }) : tr("{n} min", { n: Math.round(s / 60) }));

function Status({ h, me, onChange }) {
  const { t } = useT();
  const [msg, setMsg] = useState("");
  if (!h) return null;
  const state = h.paused ? t("Paused") : h.running ? t("Running") : h.mode === "replay_done" ? t("Replay finished") : t("Not running");
  const lagging = h.queue_lag_s > 300;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{t("Telegram watcher")}</h2>
        <div className="row-actions">
          {can(me, "IO") && <button className="btn btn-sm" onClick={async () => { try { const r = await api.watcherExport(); setMsg(t("{n} labelled posts written to {dir}", { n: r.posts, dir: r.dir })); } catch (e) { setMsg(e.message); } }}>
            <Icon name="download" size={16} /> {t("Export decisions to research")}</button>}
          {can(me, "SUPERVISOR") && !h.paused_in_config && (
            <button className="btn btn-sm" onClick={async () => onChange(await api.watcherPause(!h.paused))}>
              {h.paused ? t("Resume") : t("Pause")}</button>)}
        </div>
      </div>
      <dl className="sys">
        <dt>{t("State")}</dt><dd className={h.running && !h.paused ? "ok-text" : "err"}>{state}{h.running && h.mode === "replay" && ` · ${t("replay")}`}{h.paused_in_config && ` · ${t("paused in watcher.yaml")}`}</dd>
        <dt>{t("Last heartbeat")}</dt><dd>{h.heartbeat ? timeAgo(h.heartbeat) : t("never")}</dd>
        <dt>{t("Polling behind schedule")}</dt><dd className={lagging ? "err" : ""}>{secs(h.queue_lag_s)}</dd>
        <dt>{t("Published → processed (median)")}</dt><dd>{secs(h.processing_lag_s)}</dd>
        <dt>{t("Last 24 h")}</dt><dd>{t("{h} high · {m} medium · {l} low", { h: h.last_24h.HIGH, m: h.last_24h.MEDIUM, l: h.last_24h.LOW })}</dd>
        <dt>{t("Review queue")}</dt><dd>{h.review_queue}</dd>
      </dl>
      {msg && <p className="note">{msg}</p>}
      {h.channels.length > 0 && (
        <div className="tbl-wrap"><table className="tbl tbl-tight">
          <thead><tr><th>{t("Channel")}</th><th>{t("Last poll")}</th><th>{t("Next poll")}</th><th>{t("Every")}</th><th>{t("Posts")}</th><th>{t("Status")}</th></tr></thead>
          <tbody>{h.channels.map((c) => (
            <tr key={c.username}>
              <td>@{c.username}{c.label && <div className="muted small">{c.label}</div>}</td>
              <td>{timeAgo(c.last_poll_at)}</td>
              <td className={c.overdue_s > 300 ? "err" : ""}>{c.next_poll_at ? (c.overdue_s ? t("overdue {t}", { t: secs(c.overdue_s) }) : istTime(c.next_poll_at)) : "–"}</td>
              <td>{c.interval_s ? secs(c.interval_s) : "–"}</td>
              <td>{c.posts_seen}</td>
              <td className={c.last_error ? "err" : "ok-text"}>{c.last_error || t("ok")}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </section>
  );
}

function AlertItem({ a, me, onDecided, onEntity }) {
  const { t } = useT();
  const level = a.level || (a.route === "HIGH" ? "High" : "Medium");
  return (
    <div className={`post-row lvl-${level.toLowerCase()}`}>
      <RiskBadge level={level} score={a.score} />
      <div className="pr-main">
        <div className="pr-top">
          <Link to={`/case/${a.post_id}`} className="pr-case">{caseId(a.post_id)}</Link>
          <span className="pr-cat">{t(a.category_label)}</span>
          <span className="chip">{a.route === "HIGH" ? t("alert") : t("review queue")}</span>
          {a.district && <span className="chip chip-dist">{t(a.district)}</span>}
          {a.identifiers > 0 && <span className="chip chip-ring">{t(a.identifiers === 1 ? "{n} identifier" : "{n} identifiers", { n: a.identifiers })}</span>}
          {a.mode === "replay" && <span className="chip">{t("replay")}</span>}
          {a.decision && <span className={`chip ${a.decision.decision === "confirm" ? "chip-ok" : a.decision.decision === "needs_info" ? "chip-warn" : ""}`}>
            {t({ confirm: "confirmed", false_alarm: "false alarm", needs_info: "needs info" }[a.decision.decision])} · {a.decision.reviewer}</span>}
        </div>
        <div className="pr-excerpt">{a.text || t("(image only)")}</div>
        <div className="pr-meta">
          <a href={a.link} target="_blank" rel="noreferrer noopener">@{a.channel}</a> · {timeAgo(a.posted_at)} · p {a.p.toFixed(2)}
          {a.cues.length > 0 && <> · {t("cues")}: {a.cues.join(", ")}</>}
        </div>
        <div className="pr-why">{Object.entries(a.breakdown).filter(([k, v]) => ["model", "new_identifier", "rajasthan_place", "burst", "cross_channel"].includes(k) && v)
          .map(([k, v]) => `${t({ model: "model", new_identifier: "new identifier", rajasthan_place: "Rajasthan place", burst: "channel burst", cross_channel: "seen in 3+ channels" }[k])} +${Math.round(v)}`).join(" · ")}</div>
        {a.ident_hashes.length > 0 && (
          <div className="ring-ids">{a.ident_hashes.map((k) => (
            <button key={k} className="linkish small" onClick={() => onEntity(k)} title={t("Channels and posts with this identifier")}>
              {t(KIND[k.split(":")[0]] || k.split(":")[0])} <code>{k.split(":")[1].slice(0, 8)}</code></button>))}</div>
        )}
        <div className="row-actions">
          <DecisionButtons alertId={a.alert_id} postId={a.post_id} current={a.decision?.decision} onDone={onDecided} />
          {can(me, "IO") && <button className="btn btn-sm" onClick={() => api.evidencePdf(a.post_id)}><Icon name="pdf" size={16} /> {t("Evidence PDF")}</button>}
        </div>
      </div>
    </div>
  );
}

function Entity({ hash, onClose, onOpen }) {
  const { t } = useT();
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); api.watcherEntity(hash).then(setD).catch(() => {}); }, [hash]);
  if (!d) return null;
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t(KIND[d.kind] || d.kind)} <code className="hash">{d.hash.split(":")[1]}</code></h2>
        <button className="icon-btn" onClick={onClose} aria-label={t("Close")}><Icon name="x" size={16} /></button></div>
      <p className="muted small">{t("First seen {when} in @{ch}. The value itself is never stored: this is its keyed hash.", { when: istTime(d.first_seen), ch: d.first_channel })}</p>
      <div className="tbl-wrap"><table className="tbl tbl-tight">
        <thead><tr><th>{t("Channel")}</th><th>{t("Posts")}</th><th>{t("First seen")}</th><th>{t("Last seen")}</th></tr></thead>
        <tbody>{d.channels.map((c) => <tr key={c.channel}><td>@{c.channel}</td><td>{c.posts}</td><td>{istTime(c.first_seen)}</td><td>{istTime(c.last_seen)}</td></tr>)}</tbody>
      </table></div>
      <div className="feed">{d.posts.map((p) => (
        <div key={p.watch_id} className="mini-post">
          <span className={`risk risk-${p.route === "HIGH" ? "high" : p.route === "MEDIUM" ? "medium" : "low"}`}><b>{Math.round(p.score)}</b></span>
          {" "}{p.post_id ? <Link to={`/case/${p.post_id}`}>{caseId(p.post_id)}</Link> : <span className="muted">{t("stored only")}</span>}
          {" · "}@{p.channel} · {istTime(p.posted_at)}<div className="small">{p.text}</div>
          <div className="small muted">{t(CAT_LABEL[p.category] || p.category)}</div>
        </div>))}</div>
      <button className="linkish small" onClick={() => onOpen(null)}>{t("Back to the identifier list")}</button>
    </section>
  );
}

function Entities({ onOpen }) {
  const { t } = useT();
  const { version } = useLive();
  const [rows, setRows] = useState([]);
  useEffect(() => { api.watcherEntities().then(setRows).catch(() => {}); }, [version]);
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Identifiers across channels")}</h2></div>
      {rows.length ? (
        <div className="ids">{rows.slice(0, 15).map((e) => (
          <button key={e.hash} className="id-row linkish" onClick={() => onOpen(e.hash)}>
            <span className="id-kind">{t(KIND[e.kind] || e.kind)}</span><code>{e.hash.split(":")[1]}</code>
            <b>{t("{c} channels · {p} posts", { c: e.channels, p: e.posts })}</b>
          </button>))}</div>
      ) : <p className="muted">{t("None yet.")}</p>}
    </section>
  );
}

function Bursts() {
  const { t } = useT();
  const { version } = useLive();
  const [data, setData] = useState([]);
  const [ch, setCh] = useState("");
  const [table, setTable] = useState(false);
  useEffect(() => { api.watcherBursts().then((d) => { setData(d); setCh((c) => c || d[0]?.channel || ""); }).catch(() => {}); }, [version]);
  const b = data.find((x) => x.channel === ch);
  if (!data.length) return null;
  const labels = b ? b.counts.map((_, i) => istTime(new Date(new Date(b.start + "Z").getTime() + i * 3600e3).toISOString().slice(0, 19))) : [];
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{t("Posting bursts")}</h2>
        <div className="row-actions">
          <select value={ch} onChange={(e) => setCh(e.target.value)} aria-label={t("Channel")}>
            {data.map((x) => <option key={x.channel} value={x.channel}>@{x.channel}{x.burst_hours ? ` · ${t("{n} burst hours", { n: x.burst_hours })}` : ""}</option>)}
          </select>
          <button className="btn btn-sm" onClick={() => setTable(!table)}>{table ? t("Chart") : t("Table")}</button>
        </div>
      </div>
      {b && <p className="muted small">{t("Posts per hour, last {h} h to the newest post. Usual rate {m}/h; a burst is 3 or more posts and over 3× the usual rate. Peak {p}, {n} burst hours.", { h: b.counts.length, m: b.mean_hourly.toFixed(2), p: b.peak, n: b.burst_hours })}</p>}
      {b && !table && (
        <div className="chart-box">
          <Bar data={{
            labels,
            datasets: [
              { type: "bar", label: tr("Flagged (medium/high)"), data: b.flagged, backgroundColor: "#d7263d", borderRadius: 3, stack: "s", order: 2 },
              { type: "bar", label: tr("Other"), data: b.counts.map((c, i) => c - b.flagged[i]), backgroundColor: "#c5cbe0", borderRadius: 3, stack: "s", order: 2 },
              { type: "line", label: tr("Usual rate (7-day mean)"), data: b.counts.map(() => b.mean_hourly), borderColor: "#5b6478", borderWidth: 2, borderDash: [4, 4], pointRadius: 0, order: 1 },
              { type: "line", label: tr("Burst threshold (3×, min 3)"), data: b.counts.map(() => Math.max(3, 3 * b.mean_hourly)), borderColor: "#1b2a4a", borderWidth: 2, borderDash: [2, 3], pointRadius: 0, order: 1 },
            ],
          }} options={{ maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
            plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
            scales: { x: { stacked: true, grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#eef0f5" }, title: { display: true, text: tr("posts per hour") } } } }} />
        </div>
      )}
      {b && table && (
        <div className="tbl-wrap"><table className="tbl tbl-tight">
          <thead><tr><th>{t("Hour (IST)")}</th><th>{t("Posts")}</th><th>{t("Flagged")}</th></tr></thead>
          <tbody>{b.counts.map((c, i) => c > 0 && <tr key={i}><td>{labels[i]}</td><td>{c}</td><td>{b.flagged[i]}</td></tr>)}</tbody>
        </table></div>
      )}
    </section>
  );
}

export default function Watcher() {
  const { t } = useT();
  const { me } = useAuth();
  const { version } = useLive();
  const [h, setH] = useState(null);
  const [feed, setFeed] = useState(null);
  const [f, setF] = useState({ district: "", category: "", route: "HIGH,MEDIUM", decided: "" });
  const [entity, setEntity] = useState(null);

  const load = () => {
    api.watcherHealth().then(setH).catch(() => {});
    api.watcherAlerts(f).then(setFeed).catch(() => {});
  };
  useEffect(load, [version, f]);
  useEffect(() => { const i = setInterval(() => api.watcherHealth().then(setH).catch(() => {}), 10000); return () => clearInterval(i); }, []);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));

  return (
    <div>
      <div className="page-head">
        <h1>{t("Telegram watcher")}</h1>
        <p>{t("Approved public Telegram channels are read every 2–15 minutes. High-risk posts raise an alert here and on the duty officer's Telegram; medium ones wait in the review queue.")}</p>
      </div>
      <div className="dash-grid">
        <section className="panel feed-panel">
          <div className="panel-head"><h2>{t("Live alerts")}</h2>{feed && <span className="muted small">{t("{n} to review", { n: feed.review_queue })}</span>}</div>
          <div className="filters">
            <select value={f.district} onChange={(e) => set("district", e.target.value)} aria-label={t("District")}>
              <option value="">{t("All districts")}</option>
              {(feed?.districts || []).map(([d, n]) => <option key={d} value={d}>{t(d)} ({n})</option>)}
            </select>
            <select value={f.category} onChange={(e) => set("category", e.target.value)} aria-label={t("Category")}>
              <option value="">{t("All categories")}</option>
              {CATS.map((c) => <option key={c} value={c}>{t(CAT_LABEL[c])}</option>)}
            </select>
            <div className="seg">
              {[["HIGH,MEDIUM", "All"], ["HIGH", "Alerts"], ["MEDIUM", "Review queue"]].map(([v, l]) => (
                <button key={v} className={`seg-btn${f.route === v ? " on" : ""}`} onClick={() => set("route", v)}>{t(l)}</button>))}
            </div>
            <select value={f.decided} onChange={(e) => set("decided", e.target.value)} aria-label={t("Decision")}>
              <option value="">{t("Any decision")}</option>
              <option value="no">{t("Not reviewed")}</option>
              <option value="yes">{t("Reviewed")}</option>
            </select>
          </div>
          <div className="feed">
            {feed?.items?.length ? feed.items.map((a) => <AlertItem key={a.watch_id} a={a} me={me} onDecided={load} onEntity={setEntity} />)
              : <Empty title={t("No watcher alerts")}>{t("Approve channels in research/config/channels.discovered.yaml and start the watcher (./run.sh watcher), or replay collected posts (./run.sh watcher --replay FILE).")}</Empty>}
          </div>
        </section>
        <div className="dash-side">
          {entity ? <Entity hash={entity} onClose={() => setEntity(null)} onOpen={setEntity} /> : <Entities onOpen={setEntity} />}
          <Bursts />
          <Status h={h} me={me} onChange={setH} />
        </div>
      </div>
    </div>
  );
}
