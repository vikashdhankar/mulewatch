import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { api, caseId, timeAgo } from "../api";
import { Icon, RiskBadge } from "../components/ui";
import { useLive } from "../live";
import { Link } from "react-router-dom";
import { BotPanel } from "../components/ReportBot";

export default function Sources() {
  const { t } = useT();
  const { version } = useLive();
  const [data, setData] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState(null);
  const [kind, setKind] = useState("forum");
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => { api.sources().then(setData); api.alerts().then(setAlerts); api.stats().then(setStats); };
  useEffect(load, [version]);
  useEffect(() => { const t = setInterval(() => api.sources().then(setData), 4000); return () => clearInterval(t); }, []);

  const add = async (e) => {
    e.preventDefault();
    try { setData(await api.addSource(kind, url, "")); setUrl(""); setMsg(""); } catch (x) { setMsg(x.message); }
  };
  const sys = stats?.system;

  return (
    <div>
      <div className="page-head">
        <h1>{t("Monitored sources")}</h1>
        <p>{t("Public pages MuleWatch crawls every few seconds. New posts are scored the moment they appear.")}</p>
      </div>
      <section className="panel">
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>{t("Source")}</th><th>{t("Address")}</th><th>{t("Status")}</th><th>{t("Last crawl")}</th><th>{t("Posts collected")}</th><th>{t("Active")}</th></tr></thead>
          <tbody>{data?.sources.map((s) => (
            <tr key={s.id}>
              <td>{s.name}<div className="muted small">{t({ forum: "Public forum", telegram: "Telegram public channel", page: "Single web page, new case when it changes" }[s.kind] || s.kind)}</div></td>
              <td><code>{s.url}</code></td>
              <td className={s.last_status?.startsWith("error") || s.last_status?.includes("update the forum") ? "err" : "ok-text"}>{s.last_status || t("waiting")}</td>
              <td>{timeAgo(s.last_crawl)}</td>
              <td>{s.items_seen}</td>
              <td><label className="switch"><input type="checkbox" checked={s.enabled} onChange={async (e) => setData(await api.toggleSource(s.id, e.target.checked))} /><span /></label></td>
            </tr>
          ))}</tbody>
        </table></div>
        <form className="src-form" onSubmit={add}>
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("Source type")}>
            <option value="forum">{t("Forum (Charcha-compatible)")}</option>
            <option value="telegram">{t("Telegram public channel")}</option>
            <option value="page">{t("Single web page (checked every minute)")}</option>
          </select>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder={{ forum: "http://103.155.85.18:8100", telegram: "t.me/channelname", page: t("https://… link to an ad, profile or listing") }[kind]} required />
          <button className="btn"><Icon name="plus" /> {t("Add source")}</button>
          <button type="button" className="btn" onClick={async () => { const r = await api.crawl(); setMsg(t("Crawled now: {n} new posts.", { n: r.new })); load(); }}><Icon name="refresh" /> {t("Crawl now")}</button>
        </form>
        {msg && <p className="note">{msg}</p>}
      </section>

      <BotPanel />
      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>{t("Alert log")}</h2><span className="muted small">{sys?.telegram_alerts ? t("Telegram push is on") : t("Telegram push off (see Phone alerts above)")}</span></div>
          {alerts.length ? alerts.slice(0, 25).map((a) => (
            <Link key={a.id} to={`/case/${a.post_id}`} className="alert-row">
              <RiskBadge level={a.level} />
              <div><strong>{caseId(a.post_id)}</strong> <span className="muted small">{timeAgo(a.created_at)}{a.channel === "telegram" && (a.delivered ? ` · ${t("sent to Telegram")}` : ` · ${t("Telegram pending")}`)}</span>
                <div className="small">{a.reason}</div></div>
            </Link>
          )) : <p className="muted">{t("No alerts yet.")}</p>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>{t("Detection engine")}</h2></div>
          <dl className="sys">
            <dt>{t("Image text reading (OCR)")}</dt><dd className={sys?.ocr ? "ok-text" : "err"}>{sys?.ocr ? t("Tesseract ready") : t("Tesseract not installed")}</dd>
            <dt>{t("Text model")}</dt><dd>{t("Character n-gram classifier, trained on {n} labelled examples, retrains on every verdict", { n: sys ? sys.model_docs[0] + sys.model_docs[1] : "–" })}</dd>
            <dt>{t("AI analyst")}</dt><dd>{sys?.llm ? t("Claude second opinion on manual checks") : t("Off (optional, set ANTHROPIC_API_KEY)")}</dd>
            <dt>{t("Telegram alerts")}</dt><dd>{sys?.telegram_alerts ? t("On") : t("Off")}</dd>
            <dt>{t("Crawler")}</dt><dd>{sys?.crawler?.running ? t("Running") : t("Stopped")}{sys?.crawler?.errors ? `, ${t("{n} errors so far", { n: sys.crawler.errors })}` : ""}</dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
