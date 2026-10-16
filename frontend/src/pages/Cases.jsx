import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, LEVELS, STATUS } from "../api";
import { Empty, PostRow } from "../components/ui";
import { useLive } from "../live";

const CATEGORIES = ["Mule Account Sale", "Account-Holder Recruitment", "Card Sale", "KYC Fraud", "Easy-Money Lure", "Reported Fraud Attempt", "Suspicious Financial Ad", "Benign"];

export default function Cases() {
  const [sp, setSp] = useSearchParams();
  const { version } = useLive();
  const [data, setData] = useState({ total: 0, items: [] });
  const [q, setQ] = useState(sp.get("q") || "");
  const levels = (sp.get("level") || "").split(",").filter(Boolean);
  const set = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: true }); };

  useEffect(() => {
    api.posts({ level: sp.get("level"), category: sp.get("category"), q: sp.get("q"), label: sp.get("label"), source: sp.get("source"),
      cluster: sp.get("cluster"), district: sp.get("district"), status: sp.get("status"), assigned: sp.get("assigned"), complaints: sp.get("complaints") === "1",
      sort: sp.get("sort") || "risk", limit: 200 }).then(setData).catch(() => {});
  }, [sp, version]);

  const toggleLevel = (l) => {
    const next = levels.includes(l) ? levels.filter((x) => x !== l) : [...levels, l];
    set("level", next.join(","));
  };

  return (
    <div>
      <div className="page-head">
        <h1>Cases</h1>
        <p>{data.total} post{data.total === 1 ? "" : "s"} match. Open one to see the evidence and record a verdict.</p>
      </div>
      <div className="filters">
        <div className="seg">
          {LEVELS.map((l) => (
            <button key={l} className={`seg-btn lv-${l.toLowerCase()}${levels.includes(l) ? " on" : ""}`} onClick={() => toggleLevel(l)}>{l}</button>
          ))}
        </div>
        <select value={sp.get("category") || ""} onChange={(e) => set("category", e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <select value={sp.get("label") || ""} onChange={(e) => set("label", e.target.value)} aria-label="Verdict">
          <option value="">Any verdict</option>
          <option value="pending">Not reviewed</option>
          <option value="confirmed">Confirmed</option>
          <option value="false_positive">False positive</option>
        </select>
        <select value={sp.get("source") || ""} onChange={(e) => set("source", e.target.value)} aria-label="Source">
          <option value="">Any source</option>
          <option value="forum">Forum posts and comments</option>
          <option value="citizen">Citizen reports</option>
          <option value="url">Checked links</option>
          <option value="page">Monitored pages</option>
          <option value="manual">Manual checks</option>
          <option value="extension">Chrome extension</option>
          <option value="telegram">Telegram channels</option>
        </select>
        <select value={sp.get("status") || ""} onChange={(e) => set("status", e.target.value)} aria-label="Case status">
          <option value="">Any status</option>
          <option value="NEW,VERIFIED,NOTICE_DRAFTED,NOTICE_SENT">Open cases</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={sp.get("assigned") || ""} onChange={(e) => set("assigned", e.target.value)} aria-label="Assigned">
          <option value="">Anyone's</option>
          <option value="me">Assigned to me</option>
          <option value="none">Not assigned</option>
        </select>
        <label className="switch"><input type="checkbox" checked={sp.get("complaints") === "1"} onChange={(e) => set("complaints", e.target.checked ? "1" : "")} /><span>Linked to complaints</span></label>
        <select value={sp.get("sort") || "risk"} onChange={(e) => set("sort", e.target.value)} aria-label="Sort">
          <option value="risk">Highest risk first</option>
          <option value="recruiter">Recruiters first</option>
          <option value="recent">Newest first</option>
        </select>
        <form onSubmit={(e) => { e.preventDefault(); set("q", q); }} className="search">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search text, phone, UPI, account, author" />
        </form>
        {sp.get("cluster") && <button className="chip chip-ring" onClick={() => set("cluster", "")}>Ring {sp.get("cluster")} ✕</button>}
        {sp.get("district") && <button className="chip chip-dist" onClick={() => set("district", "")}>{sp.get("district")} ✕</button>}
      </div>
      <div className="list">
        {data.items.length ? data.items.map((p) => <PostRow key={p.id} p={p} />)
          : <Empty title="No cases match these filters">Clear a filter or wait for new posts.</Empty>}
      </div>
    </div>
  );
}
