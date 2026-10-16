import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { useSearchParams } from "react-router-dom";
import { api, LEVELS, STATUS } from "../api";
import { Empty, PostRow } from "../components/ui";
import { useLive } from "../live";

const CATEGORIES = ["Mule Account Sale", "Account-Holder Recruitment", "Card Sale", "KYC Fraud", "Easy-Money Lure", "Reported Fraud Attempt", "Suspicious Financial Ad", "Benign"];

export default function Cases() {
  const { t } = useT();
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
        <h1>{t("Cases")}</h1>
        <p>{t(data.total === 1 ? "{n} post matches. Open one to see the evidence and record a verdict." : "{n} posts match. Open one to see the evidence and record a verdict.", { n: data.total })}</p>
      </div>
      <div className="filters">
        <div className="seg">
          {LEVELS.map((l) => (
            <button key={l} className={`seg-btn lv-${l.toLowerCase()}${levels.includes(l) ? " on" : ""}`} onClick={() => toggleLevel(l)}>{l}</button>
          ))}
        </div>
        <select value={sp.get("category") || ""} onChange={(e) => set("category", e.target.value)} aria-label={t("Category")}>
          <option value="">{t("All categories")}</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{t(c)}</option>)}
        </select>
        <select value={sp.get("label") || ""} onChange={(e) => set("label", e.target.value)} aria-label={t("Verdict")}>
          <option value="">{t("Any verdict")}</option>
          <option value="pending">{t("Not reviewed")}</option>
          <option value="confirmed">{t("Confirmed")}</option>
          <option value="false_positive">{t("False positive")}</option>
        </select>
        <select value={sp.get("source") || ""} onChange={(e) => set("source", e.target.value)} aria-label={t("Source")}>
          <option value="">{t("Any source")}</option>
          <option value="forum">{t("Forum posts and comments")}</option>
          <option value="citizen">{t("Citizen reports")}</option>
          <option value="url">{t("Checked links")}</option>
          <option value="page">{t("Monitored pages")}</option>
          <option value="manual">{t("Manual checks")}</option>
          <option value="extension">{t("Chrome extension")}</option>
          <option value="telegram">{t("Telegram channels")}</option>
          <option value="bulk">{t("Bulk link checks")}</option>
        </select>
        <select value={sp.get("status") || ""} onChange={(e) => set("status", e.target.value)} aria-label={t("Case status")}>
          <option value="">{t("Any status")}</option>
          <option value="NEW,VERIFIED,NOTICE_DRAFTED,NOTICE_SENT">{t("Open cases")}</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
        </select>
        <select value={sp.get("assigned") || ""} onChange={(e) => set("assigned", e.target.value)} aria-label={t("Assigned")}>
          <option value="">{t("Anyone's")}</option>
          <option value="me">{t("Assigned to me")}</option>
          <option value="none">{t("Not assigned")}</option>
        </select>
        <label className="switch"><input type="checkbox" checked={sp.get("complaints") === "1"} onChange={(e) => set("complaints", e.target.checked ? "1" : "")} /><span>{t("Linked to complaints")}</span></label>
        <select value={sp.get("sort") || "risk"} onChange={(e) => set("sort", e.target.value)} aria-label={t("Sort")}>
          <option value="risk">{t("Highest risk first")}</option>
          <option value="recruiter">{t("Recruiters first")}</option>
          <option value="recent">{t("Newest first")}</option>
        </select>
        <form onSubmit={(e) => { e.preventDefault(); set("q", q); }} className="search">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("Search text, phone, UPI, account, author")} />
        </form>
        {sp.get("cluster") && <button className="chip chip-ring" onClick={() => set("cluster", "")}>Ring {sp.get("cluster")} ✕</button>}
        {sp.get("district") && <button className="chip chip-dist" onClick={() => set("district", "")}>{sp.get("district")} ✕</button>}
      </div>
      <div className="list">
        {data.items.length ? data.items.map((p) => <PostRow key={p.id} p={p} />)
          : <Empty title={t("No cases match these filters")}>{t("Clear a filter or wait for new posts.")}</Empty>}
      </div>
    </div>
  );
}
