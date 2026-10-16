import { BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip } from "chart.js";
import { tr, useT } from "../i18n";
import { useEffect, useMemo, useState } from "react";
import { Bar } from "react-chartjs-2";
import { Link } from "react-router-dom";
import { api, caseId, inr } from "../api";
import { TakedownClock } from "../components/CasePolice";
import { BotCard } from "../components/ReportBot";
import { Empty, PostRow } from "../components/ui";
import { useLive } from "../live";

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend);
Chart.defaults.font.family = "IBM Plex Sans";
Chart.defaults.color = "#5b6478";

function Kpi({ label, value, tone, to }) {
  const { t } = useT();
  const body = <><strong>{value ?? "–"}</strong><span>{label}</span></>;
  return to ? <Link to={to} className={`kpi ${tone || ""}`}>{body}</Link> : <div className={`kpi ${tone || ""}`}>{body}</div>;
}

const KIND = { phone: "Phone", upi: "UPI ID", telegram: "Telegram", whatsapp: "WhatsApp", crypto_wallet: "Crypto wallet", domain: "Domain", email: "Email", account: "Account no.", ifsc: "IFSC", card: "Card no.", handle: "Handle", url: "Link" };

export default function Dashboard() {
  const { t } = useT();
  const { version, feed } = useLive();
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [flaggedOnly, setFlaggedOnly] = useState(true);
  const [err, setErr] = useState("");
  const [clocks, setClocks] = useState([]);

  useEffect(() => {
    api.clocks().then(setClocks).catch(() => {});
    api.stats().then(setStats).catch((e) => setErr(e.message));
    api.posts({ limit: 40 }).then((d) => setRecent(d.items)).catch(() => {});
  }, [version]);

  const fresh = useMemo(() => new Set(feed.filter((p) => Date.now() - p._arrived < 20000).map((p) => p.id)), [feed]);
  const items = useMemo(() => {
    const byId = new Map(recent.map((p) => [p.id, p]));
    feed.forEach((p) => { if (!byId.has(p.id)) byId.set(p.id, p); });
    return [...byId.values()].sort((a, b) => b.id - a.id)
      .filter((p) => !flaggedOnly || ["Critical", "High", "Medium"].includes(p.risk_level)).slice(0, 25);
  }, [recent, feed, flaggedOnly]);

  if (err) return <Empty title={t("Can't reach the MuleWatch API")}>{err}. Start the backend with ./run.sh and reload.</Empty>;

  const tl = stats?.timeline || [];
  return (
    <div className="dash">
      <div className="page-head">
        <h1>{t("Command center")}</h1>
        <p>{t("Every new public post is scanned for the sale or rental of bank accounts, cards and banking kits.")}</p>
      </div>

      <div className="kpis">
        <Kpi label={t("posts and comments scanned")} value={stats?.total} to="/cases" />
        <Kpi label={t("flagged high or critical")} value={stats?.flagged} tone="warn" to="/cases?level=Critical,High" />
        <Kpi label={t("critical")} value={stats?.critical} tone="crit" to="/cases?level=Critical" />
        <Kpi label={stats?.complaint_amount ? t("linked to complaints · {amount}", { amount: inr(stats.complaint_amount) }) : t("linked to victim complaints")}
          value={stats?.complaint_linked} tone="crit" to="/cases?complaints=1" />
        <Kpi label={t("seller rings found")} value={stats?.rings} tone="tone-ring" to="/network" />
        <Kpi label={stats?.my_cases ? t("open cases · {n} assigned to you", { n: stats.my_cases }) : t("open cases to act on")} value={stats?.open_cases}
          tone="ok" to="/cases?status=NEW,VERIFIED,NOTICE_DRAFTED,NOTICE_SENT&level=Critical,High&sort=recruiter" />
      </div>

      <div className="dash-grid">
        <section className="panel feed-panel">
          <div className="panel-head">
            <h2>{t("Live intercepts")}</h2>
            <label className="switch">
              <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
              <span>{t("Hide low risk")}</span>
            </label>
          </div>
          <div className="feed">
            {items.length ? items.map((p) => <PostRow key={p.id} p={p} fresh={fresh.has(p.id)} />)
              : <Empty title={t("Waiting for posts")}>{t("New posts on monitored sources appear here within seconds.")}</Empty>}
          </div>
        </section>

        <div className="dash-side">
          {clocks.length > 0 && (
            <section className="panel">
              <div className="panel-head"><h2>{t("Takedown clocks")}</h2><span className="muted small">{t("{n} notices pending", { n: clocks.length })}</span></div>
              {clocks.slice(0, 4).map((c) => (
                <Link key={c.id} to={`/case/${c.id}`} className="clock-link">
                  <span className="clock-case">{caseId(c.id)} · {t(c.category)}{c.officer && ` · ${c.officer}`}</span>
                  <TakedownClock clock={c.clock} platform={c.platform} />
                </Link>
              ))}
            </section>
          )}
          <BotCard />
          <section className="panel">
            <div className="panel-head"><h2>{t("Seller rings")}</h2><Link to="/network" className="more">{t("Open network")}</Link></div>
            {stats?.ring_list?.length ? stats.ring_list.slice(0, 5).map((r) => (
              <Link key={r.cluster_id} to={`/network?cluster=${r.cluster_id}`} className="ring">
                <div className="ring-top"><strong>{t("{n} linked posts", { n: r.size })}</strong><span>{t(r.authors.length === 1 ? "by {n} account" : "by {n} accounts", { n: r.authors.length })}</span></div>
                <div className="ring-ids">{r.identifiers.slice(0, 3).map((i) => <code key={i}>{i.split(":").slice(1).join(":")}</code>)}</div>
                <div className="ring-authors">{r.authors.slice(0, 4).map((a) => "u/" + a).join(", ")}</div>
              </Link>
            )) : <p className="muted">{t("No coordinated activity yet.")}</p>}
          </section>

          <section className="panel">
            <div className="panel-head"><h2>{t("Risk mix")}</h2></div>
            <div className="mix">
              {["critical", "high", "medium", "low"].map((l) => (
                <div key={l} className={`mix-seg mix-${l}`} style={{ flexGrow: stats?.[l] || 0 }} title={`${l}: ${stats?.[l]}`} />
              ))}
            </div>
            <div className="mix-legend">
              {["critical", "high", "medium", "low"].map((l) => <span key={l}><i className={`dotc mix-${l}`} />{t(l[0].toUpperCase() + l.slice(1))} {stats?.[l] ?? 0}</span>)}
            </div>
          </section>
        </div>
      </div>

      <div className="dash-lower">
        <section className="panel">
          <div className="panel-head"><h2>{t("Posts over time")}</h2></div>
          <div className="chart-box">
            <Bar data={{
              labels: tl.map((t) => t.bucket),
              datasets: [
                { label: tr("Flagged"), data: tl.map((t) => t.flagged), backgroundColor: "#d7263d", borderRadius: 3, stack: "s" },
                { label: tr("Other"), data: tl.map((t) => t.total - t.flagged), backgroundColor: "#c5cbe0", borderRadius: 3, stack: "s" },
              ],
            }} options={{ maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
              scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, ticks: { precision: 0 }, grid: { color: "#eef0f5" } } } }} />
          </div>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>{t("Words that gave sellers away")}</h2></div>
          <div className="terms">
            {(stats?.top_terms || []).map(([t, n]) => (
              <div key={t} className="term"><span>{t}</span><div className="bar"><i style={{ width: `${(n / (stats.top_terms[0][1] || 1)) * 100}%` }} /></div><b>{n}</b></div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-head"><h2>{t("Identifiers reused across posts")}</h2></div>
          <div className="ids">
            {(stats?.top_identifiers || []).length ? stats.top_identifiers.slice(0, 8).map(([k, n]) => {
              const [kind, ...v] = k.split(":");
              return <div key={k} className="id-row"><span className="id-kind">{t(KIND[kind] || kind.replace("_", " "))}</span><code>{v.join(":")}</code><b>{t("{n} posts", { n })}</b></div>;
            }) : <p className="muted">{t("None yet.")}</p>}
          </div>
        </section>
      </div>
    </div>
  );
}
