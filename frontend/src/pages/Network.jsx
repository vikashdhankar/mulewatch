import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useT } from "../i18n";
import { api, caseId } from "../api";
import NetworkGraph, { KIND_COLOR, LEVEL_COLOR } from "../components/NetworkGraph";
import { Empty, RiskBadge } from "../components/ui";
import { useLive } from "../live";

export default function Network() {
  const { t } = useT();
  const [sp, setSp] = useSearchParams();
  const { version } = useLive();
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);
  const [nbrs, setNbrs] = useState([]);
  const [minScore, setMinScore] = useState(30);
  const cluster = sp.get("cluster");

  useEffect(() => {
    api.graph(cluster ? { cluster } : { min_score: minScore }).then(setData);
  }, [cluster, minScore, version]);

  const posts = data?.nodes.filter((n) => n.type === "post").length || 0;
  const ids = data?.nodes.filter((n) => n.type !== "post").length || 0;

  return (
    <div>
      <div className="page-head">
        <h1>{t("Seller network")}</h1>
        <p>{t("Posts are joined when they share a phone number, UPI ID, Telegram/WhatsApp link or wallet, reuse the same image, or repeat near-identical text. Click any node to trace it.")}</p>
      </div>
      <div className="filters">
        {cluster ? <button className="chip chip-ring" onClick={() => setSp({})}>{t("Showing ring {n}", { n: cluster })} ✕</button> : (
          <label className="range">{t("Minimum risk score")} <input type="range" min="0" max="90" step="10" value={minScore} onChange={(e) => setMinScore(+e.target.value)} /> <b>{minScore}</b></label>
        )}
        <span className="muted small">{t("{a} posts, {b} shared identifiers", { a: posts, b: ids })}</span>
      </div>
      <div className="net-wrap">
        <section className="panel net-graph">
          {data && posts ? <NetworkGraph data={data} height={620} onSelect={(n, nb) => { setSel(n); setNbrs(nb); }} />
            : <Empty title={t("Nothing to draw yet")}>{t("Lower the minimum score or wait for flagged posts.")}</Empty>}
          <div className="net-legend">
            {Object.entries(LEVEL_COLOR).map(([k, c]) => <span key={k}><i style={{ background: c }} className="dotc" />{t("{level} risk post", { level: t(k) })}</span>)}
            {[["phone", "Phone number"], ["upi", "UPI ID"], ["telegram", "Telegram link"], ["whatsapp", "WhatsApp"], ["crypto_wallet", "Crypto wallet"]].map(([k, l]) => <span key={k}><i style={{ background: KIND_COLOR[k] }} className="dotc sq" />{t(l)}</span>)}
            <span><i className="dash-line" />{t("same image or text")}</span>
          </div>
        </section>
        <aside className="panel net-side">
          {!sel && <p className="muted">{t("Select a node to see what it connects.")}</p>}
          {sel?.type === "post" && (
            <div>
              <RiskBadge level={sel.level} score={sel.score} />
              <h3><Link to={`/case/${sel.post_id}`}>{caseId(sel.post_id)}</Link></h3>
              <p className="small muted">{sel.platform}{sel.author && ` · u/${sel.author}`}</p>
              <p>{sel.excerpt}</p>
              <h4>{t("Connected identifiers")}</h4>
              {nbrs.filter((n) => n.type !== "post").map((n) => <div key={n.id} className="id-row"><span className="id-kind">{t(n.kind_label)}</span><code>{n.label}</code><b>{t("{n} posts", { n: n.count })}</b></div>)}
              <Link className="btn wide" to={`/case/${sel.post_id}`}>{t("Open case")}</Link>
            </div>
          )}
          {sel && sel.type !== "post" && (
            <div>
              <span className="id-kind">{t(sel.kind_label)}</span>
              <h3><code>{sel.label}</code></h3>
              <p>{t("Used in {n} posts:", { n: sel.count })}</p>
              {nbrs.filter((n) => n.type === "post").map((n) => (
                <Link key={n.id} to={`/case/${n.post_id}`} className="mini-post">
                  <RiskBadge level={n.level} score={n.score} /><span>{n.excerpt}</span>
                </Link>
              ))}
              <button className="btn wide" onClick={() => api.addWatch(sel.type === "domain" ? "url" : sel.type, sel.label, "from network view")}>{t("Add to watchlist")}</button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
