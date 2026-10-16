import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, can, caseId, timeAgo } from "../api";
import { useAuth } from "../auth";
import { BanksPanel, ComplaintsPanel, DraftEditor, DraftsPanel, EvidencePanel, JurisdictionPanel, RecruiterCard, RepostBanner, TakedownClock, WorkflowPanel } from "../components/CasePolice";
import NetworkGraph from "../components/NetworkGraph";
import { Empty, Entities, GROUP_CLASS, GROUP_LABEL, HighlightedText, Icon, Legend, PostRow, RiskBadge, ScoreBreakdown, ScoreMeter } from "../components/ui";
import { useLive } from "../live";

export function Evidence({ p, onWatch, watched }) {
  const { t } = useT();
  const imageMatches = (p.matches || []).filter((m) => m.source === "image");
  return (
    <>
      <section className="panel">
        <div className="panel-head"><h2>{t("Post content")}</h2><Legend /></div>
        <HighlightedText text={p.text} matches={p.matches} entitySpans={p.scores?.entity_spans} />
        {p.image && (
          <div className="img-ev">
            <a href={p.image} target="_blank" rel="noreferrer"><img src={p.image} alt={t("Image attached to the post")} /></a>
            <div>
              <h3>{t("Text read from the image")}</h3>
              {p.ocr_text ? <p className="ocr">{p.ocr_text}</p> : <p className="muted">{t("No readable text found (is Tesseract installed?).")}</p>}
              {imageMatches.length > 0 && (
                <p className="img-hits">{t("Words found in the image:")} {[...new Map(imageMatches.map((m) => [m.term, m])).values()].map((m) => <mark key={m.term} className={GROUP_CLASS[m.group]} title={t(GROUP_LABEL[m.group] || "")}>{m.term}</mark>)}</p>
              )}
            </div>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-head"><h2>{t("Why it was flagged")}</h2></div>
        {p.reasons?.length ? <ul className="reasons">{p.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p className="muted">{t("No risk indicators found.")}</p>}
        <ScoreBreakdown scores={p.scores} llm={p.llm} />
      </section>
      <section className="panel">
        <div className="panel-head"><h2>{t("Identifiers")}</h2><span className="muted small">{t("Add one to the watchlist to alert on any future post that uses it")}</span></div>
        <Entities entities={p.entities} onWatch={onWatch} watched={watched} />
      </section>
    </>
  );
}

export default function CaseDetail() {
  const { t } = useT();
  const { id } = useParams();
  const nav = useNavigate();
  const { version } = useLive();
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [graph, setGraph] = useState(null);
  const [watched, setWatched] = useState(new Set());
  const [info, setInfo] = useState(null);
  const [draft, setDraft] = useState(null);       // {kind, bank}
  const { me } = useAuth();
  const loadInfo = () => api.police(id).then(setInfo).catch(() => {});

  const loadWatch = () => api.watchlist().then((w) => setWatched(new Set(w.map((x) => x.value.toLowerCase()))));
  useEffect(() => {
    api.post(id).then(setP).catch((e) => setErr(e.message));
    loadInfo();
    loadWatch();
  }, [id, version]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (p?.cluster_size > 1) api.graph({ post: id }).then(setGraph);
    else setGraph(null);
  }, [id, p?.cluster_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <Empty title={t("Case {id} not found", { id: caseId(id) })}>{err}</Empty>;
  if (!p) return <p className="muted">{t("Loading case…")}</p>;

  const verdict = async (label) => {
    setBusy(label);
    try { setP(await api.feedback(p.id, p.label === label ? "clear" : label)); setNote(label === "confirmed" ? t("Verdict saved. Keyword weights and the text model were updated.") : t("Marked as false positive. The model learned from it and rescored all posts.")); }
    catch (e) { setNote(e.message); }
    setBusy("");
  };
  const takedown = async () => {
    setBusy("td");
    try { const r = await api.takedown(p.id); setNote(r.ok ? t("Removed through the forum's moderation API. The case is now marked Content removed, and MuleWatch will alert if it comes back.") : r.message); api.post(id).then(setP); loadInfo(); }
    catch (e) { setNote(e.message); }
    setBusy("");
  };
  const watch = async (kind, value) => { await api.addWatch(kind, String(value), `from ${caseId(p.id)}`); loadWatch(); setNote(t("Added {v} to the watchlist.", { v: value })); };

  return (
    <div className="case">
      <button className="back" onClick={() => nav(-1)}>{t("Back")}</button>
      <div className="case-head">
        <ScoreMeter score={p.risk_score} level={p.risk_level} />
        <div className="case-title">
          <div className="case-id">{caseId(p.id)} <span className="chip">{t(p.category)}</span>
            {p.label === "confirmed" && <span className="chip chip-ok">{t("confirmed")}</span>}
            {p.label === "false_positive" && <span className="chip">{t("false positive")}</span>}
            {p.takedown && <span className="chip chip-td">{t("takedown requested")}</span>}
          </div>
          <h1>{(p.text || p.ocr_text || t("Image post")).split("\n")[0].slice(0, 120)}</h1>
          <p className="case-meta">
            {p.platform}{p.author && <> · u/{p.author}</>} · {t("posted {ago}", { ago: timeAgo(p.posted_at) })} · {t("language {l}", { l: p.language })}
            {p.url && <> · <a href={p.url} target="_blank" rel="noreferrer">{t("open original")}</a></>}
          </p>
        </div>
        <div className="case-actions">
          <button className={`btn btn-confirm${p.label === "confirmed" ? " on" : ""}`} disabled={!!busy} onClick={() => verdict("confirmed")}><Icon name="check" /> {p.label === "confirmed" ? t("Confirmed") : t("Confirm fraud")}</button>
          <button className={`btn btn-fp${p.label === "false_positive" ? " on" : ""}`} disabled={!!busy} onClick={() => verdict("false_positive")}><Icon name="x" /> {t("False positive")}</button>
          {p.source === "forum" && can(me, "IO") && <button className="btn btn-td" disabled={!!busy || !!p.takedown} onClick={takedown} title={t("Demo: uses the Charcha forum's moderation API")}><Icon name="shield" /> {p.takedown ? t("Removed on forum") : t("Remove via forum API")}</button>}
          <a className="btn" href={`/api/posts/${p.id}/report.pdf`} target="_blank" rel="noreferrer"><Icon name="pdf" /> {t("Evidence report (PDF)")}</a>
        </div>
      </div>
      {note && <div className="note" role="status">{note}</div>}
      {info && <RepostBanner info={info} />}
      {info?.clock && <TakedownClock clock={info.clock} platform={p.platform.split(" · ")[0]} />}
      {p.masked && <p className="muted small mask-note">{t("Phone and account numbers are partly hidden for your role.")}</p>}

      <div className="case-grid">
        <div className="case-main">
          {info && <ComplaintsPanel info={info} />}
          <Evidence p={p} onWatch={watch} watched={watched} />
          {info && <EvidencePanel pid={p.id} info={info} />}
        </div>
        <div className="case-side">
          {info && <WorkflowPanel pid={p.id} info={info} onChange={(x) => { setInfo(x); api.post(id).then(setP); }} />}
          {info && <DraftsPanel info={info} onOpen={(kind) => setDraft({ kind, bank: info.banks[0]?.bank_code || "?" })} />}
          {info && <RecruiterCard info={info} />}
          {info && <JurisdictionPanel info={info} />}
          {info && <BanksPanel pid={p.id} info={info} onDraft={info.can_act ? (kind, bank) => setDraft({ kind, bank }) : null} />}
          <section className="panel">
            <div className="panel-head"><h2>{t("Linked posts")}</h2>{p.cluster_id != null && <Link className="more" to={`/network?cluster=${p.cluster_id}`}>{t("Full network")}</Link>}</div>
            {graph && <NetworkGraph data={graph} height={260} compact onSelect={(n) => n?.post_id && n.post_id !== p.id && nav(`/case/${n.post_id}`)} />}
            {p.related?.length ? p.related.map((r) => <PostRow key={r.id} p={r} why={r.why} />)
              : <p className="muted">{t("Not linked to any other post by text, image or identifiers.")}</p>}
          </section>
          {p.citizen_reports?.length > 0 && (
            <section className="panel">
              <div className="panel-head"><h2>{t("Citizen reports ({n})", { n: p.citizen_reports.length })}</h2></div>
              <p className="small muted">{t("Reported through the Telegram bot. Reporters are told when you confirm, dismiss or take this down.")}</p>
              {p.citizen_reports.map((r, i) => (
                <div key={i} className="cit-row"><b>{r.reporter}</b><span>{r.origin}</span><span className="muted small">{timeAgo(r.at)}</span></div>
              ))}
            </section>
          )}
          <section className="panel">
            <div className="panel-head"><h2>{t("Record hash")}</h2></div>
            <p className="small">{t("SHA-256 of the captured post, metadata and image, recorded at capture time:")}</p>
            <code className="hash">{p.evidence_hash}</code>
          </section>
        </div>
      </div>
      {draft && info && (
        <DraftEditor pid={p.id} kind={draft.kind} bank={draft.bank} label={t(info.drafts.find((d) => d.kind === draft.kind)?.label || "")}
          onClose={() => setDraft(null)} onExported={() => { loadInfo(); setNote(t("Draft downloaded. The export is recorded in the case's chain of custody.")); }} />
      )}
    </div>
  );
}

export { RiskBadge };
