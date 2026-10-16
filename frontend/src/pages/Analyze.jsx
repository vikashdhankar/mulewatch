import { useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../i18n";
import { api, caseId } from "../api";
import { ScoreMeter } from "../components/ui";
import { Evidence } from "./CaseDetail";

const SAMPLES = [
  "HDFC current account available — full kit with ATM + passbook + net banking. KYC done, 15k. Telegram t.me/fastkit_99",
  "Bhai apna khata kiraye pe do, har mahine 25k milega. Sirf gaming ke liye use hoga. WhatsApp 98765 43210",
  "Beware: never sell or rent your bank account, it makes you a money mule. Report to 1930.",
  "Selling my old cycle, ₹3000. Call 91234 56780",
];

export default function Analyze() {
  const { t } = useT();
  const [mode, setMode] = useState("link");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [image, setImage] = useState(null);
  const [save, setSave] = useState(false);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(""); setRes(null);
    try {
      if (mode === "link") {
        setRes(await api.analyzeUrl(url, save));
      } else {
        const f = new FormData();
        f.append("text", text);
        f.append("save", save ? "true" : "false");
        if (image) f.append("image", image);
        setRes(await api.analyze(f));
      }
    } catch (x) { setErr(x.message); }
    setBusy(false);
  };

  const canRun = mode === "link" ? url.trim().length > 3 : (text.trim() || image);
  const fetched = res?.fetch;

  return (
    <div>
      <div className="page-head">
        <h1>{t("Check a post")}</h1>
        <p>{t("Paste a link to a post, ad, Telegram post or image, or paste the text and a screenshot. You get the verdict and the evidence in a few seconds.")}</p>
      </div>
      <form className="panel analyze" onSubmit={run}>
        <div className="seg mode-seg" role="tablist">
          <button type="button" role="tab" aria-selected={mode === "link"} className={`seg-btn${mode === "link" ? " on-indigo" : ""}`} onClick={() => setMode("link")}>{t("Link")}</button>
          <button type="button" role="tab" aria-selected={mode === "text"} className={`seg-btn${mode === "text" ? " on-indigo" : ""}`} onClick={() => setMode("text")}>{t("Text or screenshot")}</button>
        </div>
        {mode === "link" ? (
          <>
            <input className="url-in" value={url} onChange={(e) => setUrl(e.target.value)} type="text" inputMode="url" autoFocus
              placeholder={t("https://t.me/channel/123, an OLX/Facebook/Instagram/X post, a forum post or an image link")} aria-label={t("Link to check")} />
            <p className="hint-line">{t("MuleWatch opens the link like a browser, reads the post text, the link-preview details and any pictures (text in images is read by OCR). Pages that need a login may show little; use the text tab or the Chrome extension for those.")}</p>
          </>
        ) : (
          <>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder={t("Paste the post text here (English, Hindi or Hinglish)")} />
            <div className="samples">{t("Try:")} {SAMPLES.map((s, i) => <button type="button" key={i} onClick={() => setText(s)}>{t("sample {n}", { n: i + 1 })}</button>)}</div>
          </>
        )}
        <div className="analyze-row">
          {mode === "text" && <label className="file-in">{t("Screenshot or poster")} <input type="file" accept="image/*" onChange={(e) => setImage(e.target.files[0] || null)} /></label>}
          <label className="switch"><input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} /><span>{t("Save as a case")}</span></label>
          <button className="btn btn-primary" disabled={busy || !canRun}>{busy ? (mode === "link" ? t("Opening link…") : t("Checking…")) : t("Check post")}</button>
        </div>
        {err && <p className="err" role="alert">{err}</p>}
      </form>
      {res && (
        <div className="analyze-res">
          {fetched && (
            <div className={`fetch-info${fetched.note ? " warn" : ""}`}>
              {fetched.already_tracked
                ? <>{t("This link is already a case:")} <Link to={`/case/${res.id}`}>{caseId(res.id)}</Link></>
                : <>{t("Read from")} <a href={fetched.final_url} target="_blank" rel="noreferrer">{fetched.final_url}</a> · {t(fetched.how)}{fetched.images ? ` · ${t("{n} images", { n: fetched.images })}` : ""}</>}
              {fetched.note && <p>{fetched.note}</p>}
            </div>
          )}
          <div className="case-head">
            <ScoreMeter score={res.risk_score} level={res.risk_level} />
            <div className="case-title">
              <div className="case-id">{t(res.category)}{res.cluster_size > 1 && <span className="chip chip-ring">{t("linked to {n} other posts", { n: res.cluster_size - 1 })}</span>}</div>
              <h1>{res.risk_level === "Low" ? t("No strong signs of account or card selling") : t("This looks like a suspicious financial ad")}</h1>
              <p className="case-meta">{res.platform}{res.author && <> · {res.author}</>}</p>
              {res.id && <p><Link to={`/case/${res.id}`}>{t("Open case")} {caseId(res.id)}</Link></p>}
            </div>
          </div>
          <Evidence p={res} />
        </div>
      )}
    </div>
  );
}
