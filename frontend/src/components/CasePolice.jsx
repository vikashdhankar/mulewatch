import { useEffect, useState } from "react";
import { T, useT } from "../i18n";
import { Link } from "react-router-dom";
import { api, can, caseId, inr, istTime, STATUS } from "../api";
import { useAuth } from "../auth";
import { Icon, Modal, StatusChip } from "./ui";

const FLOW = ["NEW", "VERIFIED", "NOTICE_DRAFTED", "NOTICE_SENT", "CONTENT_REMOVED", "FIR_LINKED"];

function useNow(active) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const utc = (iso) => new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();

function fmtLeft(ms) {
  const s = Math.max(0, Math.floor(Math.abs(ms) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

/** The platform's removal window, ticking. */
export function TakedownClock({ clock, platform }) {
  const { t } = useT();
  const running = clock && !clock.removed_at;
  const now = useNow(running);
  if (!clock) return null;
  if (clock.removed_at) {
    return (
      <div className={`clock clock-${clock.state}`}>
        <Icon name="clock" />
        <div><b>{clock.state === "met" ? t("Removed within the window") : t("Removed after the window ran out")}</b>
          <span>{t("{p} took {d} after the notice ({h} h allowed)", { p: platform, d: clock.took_minutes < 120 ? t("{n} min", { n: clock.took_minutes }) : t("{n} h", { n: (clock.took_minutes / 60).toFixed(1) }), h: clock.window_hours })}</span></div>
      </div>
    );
  }
  const left = utc(clock.deadline) - now;
  const state = left <= 0 ? "overdue" : left <= 30 * 60000 ? "warn" : "running";
  const pct = Math.min(100, Math.max(0, 100 - (left / (clock.window_hours * 3600000)) * 100));
  return (
    <div className={`clock clock-${state}`} role="timer">
      <Icon name="clock" />
      <div className="clock-body">
        <b>{state === "overdue" ? t("Overdue by {d}", { d: fmtLeft(left) }) : t("{d} left", { d: fmtLeft(left) })}</b>
        <span>{state === "overdue" ? t("{p} has not removed the content within {h} h of the notice. Escalate or record non-compliance.", { p: platform, h: clock.window_hours })
          : t("for {p} to remove the content · notice sent {when} IST", { p: platform, when: istTime(clock.sent_at) })}</span>
        <div className="clock-bar"><i style={{ width: `${pct}%` }} /></div>
      </div>
    </div>
  );
}

export function WorkflowPanel({ pid, info, onChange }) {
  const { t } = useT();
  const { me } = useAuth();
  const [users, setUsers] = useState([]);
  const [fir, setFir] = useState(info.fir_number);
  const [ps, setPs] = useState(info.police_station || info.jurisdiction?.police_station || "");
  const [notes, setNotes] = useState(info.notes);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api.users().then(setUsers).catch(() => {}); }, []);
  useEffect(() => { setFir(info.fir_number); setNotes(info.notes); setPs(info.police_station || info.jurisdiction?.police_station || ""); },
    [info.fir_number, info.notes, info.police_station]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (data, what) => {
    setBusy(what); setErr("");
    try { onChange(await api.updateCase(pid, data)); } catch (e) { setErr(e.message); }
    setBusy("");
  };
  const officers = users.filter((u) => u.active && (u.role === "IO" || u.role === "SUPERVISOR"));
  const idx = FLOW.indexOf(info.status);
  const dirty = fir !== info.fir_number || notes !== info.notes || ps !== (info.police_station || info.jurisdiction?.police_station || "");

  return (
    <section className="panel wf">
      <div className="panel-head"><h2>{t("Case workflow")}</h2><StatusChip status={info.status} /></div>
      <ol className="steps">
        {FLOW.map((s, i) => (
          <li key={s} className={info.status === "CLOSED_NO_ACTION" ? "" : i < idx ? "done" : i === idx ? "now" : ""}>{t(STATUS[s])}</li>
        ))}
      </ol>
      {info.status === "CLOSED_NO_ACTION" && <p className="muted small">{t("This case was closed without action.")}</p>}
      {info.can_act ? (
        <>
          {info.allowed_next.length > 0 && (
            <div className="wf-actions">
              {info.allowed_next.map((n) => (
                <button key={n.status} className={`btn${["VERIFIED", "NOTICE_SENT", "CONTENT_REMOVED", "FIR_LINKED"].includes(n.status) ? " btn-primary" : ""}`}
                  disabled={!!busy} onClick={() => save({ status: n.status, fir_number: fir }, n.status)}>
                  {n.status === "NOTICE_SENT" ? t("Mark notice sent (starts clock)") : n.status === "NEW" ? t("Reopen") : t("Mark: {s}", { s: t(n.label) })}
                </button>
              ))}
            </div>
          )}
          <div className="wf-grid">
            <label>Assigned to
              {info.can_assign_others ? (
                <select value={info.assigned_to?.id || ""} disabled={!!busy}
                  onChange={(e) => save({ assigned_to: e.target.value ? Number(e.target.value) : null }, "assign")}>
                  <option value="">{t("Not assigned")}</option>
                  {officers.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.designation || u.role})</option>)}
                </select>
              ) : (
                <div className="wf-assign">
                  <span>{info.assigned_to ? info.assigned_to.name : t("Not assigned")}</span>
                  {!info.assigned_to && <button className="linkish" onClick={() => save({ assigned_to: me.id }, "assign")}>{t("Take this case")}</button>}
                  {info.assigned_to?.id === me.id && <button className="linkish" onClick={() => save({ assigned_to: null }, "assign")}>{t("Release")}</button>}
                </div>
              )}
            </label>
            <label>{t("FIR number")}<input value={fir} onChange={(e) => setFir(e.target.value)} placeholder="e.g. 123/2026" /></label>
            <label className="span2">{t("Police station")}<input value={ps} onChange={(e) => setPs(e.target.value)} placeholder={t("Cyber Police Station, …")} /></label>
            <label className="span2">{t("Case notes")}<textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("What was done, who was contacted, reference numbers…")} /></label>
          </div>
          {dirty && <button className="btn" disabled={!!busy} onClick={() => save({ fir_number: fir, police_station: ps, notes }, "details")}>{t("Save details")}</button>}
        </>
      ) : (
        <dl className="sys small">
          <dt>{t("Assigned to")}</dt><dd>{info.assigned_to ? info.assigned_to.name : t("Not assigned")}</dd>
          {info.fir_number && <><dt>{t("FIR")}</dt><dd>{info.fir_number}</dd></>}
          <dt>{t("Next steps")}</dt><dd className="muted">{t("An Investigating Officer takes the case from here.")}</dd>
        </dl>
      )}
      {err && <p className="err small">{err}</p>}
    </section>
  );
}

export function RecruiterCard({ info }) {
  const { t } = useT();
  if (!info.recruiter_score) return null;
  const s = Math.round(info.recruiter_score);
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Recruiter priority")}</h2><span className={`prio ${s >= 60 ? "hi" : s >= 30 ? "mid" : ""}`}>{s}/100</span></div>
      <ul className="reasons small">{info.recruiter_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
      <p className="muted small">{t("Recruiters and bulk resellers are ranked above people selling one account, who are often victims themselves.")}</p>
    </section>
  );
}

export function ComplaintsPanel({ info }) {
  const { t } = useT();
  const c = info.complaints;
  if (!c.count) return null;
  return (
    <section className="panel panel-comp">
      <div className="panel-head"><h2>{t("Victim complaints ({n})", { n: c.count })}</h2><b className="money">{t("{amount} lost", { amount: inr(c.amount) })}</b></div>
      {c.items ? (
        <div className="tbl-wrap"><table className="tbl tbl-tight">
          <thead><tr><th>{t("Complaint")}</th><th>{t("Date")}</th><th>{t("Amount")}</th><th>{t("District")}</th><th>{t("Matched on")}</th></tr></thead>
          <tbody>{c.items.map((x) => (
            <tr key={x.id}>
              <td><code>{x.complaint_id}</code>{x.category && <div className="muted small">{x.category}</div>}</td>
              <td className="small">{x.date}</td><td>{x.amount ? inr(x.amount) : "—"}</td><td>{x.district}</td>
              <td className="small">{x.identifiers.filter((i) => i.shared).map((i) => <code key={i.value} className="shared">{i.value}</code>)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="muted small">{t("The identifiers in this ad appear in {n} victim complaints. Complaint details are visible to Investigating Officers.", { n: c.count })}</p>}
    </section>
  );
}

export function BanksPanel({ pid, info, onDraft }) {
  const { t } = useT();
  if (!info.banks?.length) return null;
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Banks and payment apps")}</h2></div>
      {info.banks.map((g) => (
        <div key={g.bank_code || "?"} className="bank">
          <div className="bank-head"><Icon name="bank" size={16} /><b>{g.bank}</b>{g.bank_code && <code>{g.bank_code}</code>}
            {onDraft && <button className="linkish" onClick={() => onDraft("bank", g.bank_code || "?")}>{t("Draft request")}</button>}</div>
          {g.items.map((it) => (
            <div key={it.value} className="bank-item"><span className="id-kind">{t(it.kind)}</span><code>{it.value}</code><span className="muted small">{it.detail}</span></div>
          ))}
        </div>
      ))}
    </section>
  );
}

export function JurisdictionPanel({ info }) {
  const { t } = useT();
  const j = info.jurisdiction || {};
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Suggested jurisdiction")}</h2>{j.confidence && j.confidence !== "none" && <span className="chip">{t(j.confidence === "medium" ? "medium confidence" : "low confidence")}</span>}</div>
      {j.district ? (
        <p className="juris"><Icon name="pin" size={16} /><b>{t(j.district)}</b> <span className="muted">({j.district})</span> → {t("Cyber Police Station, {d}", { d: t(j.district) })}</p>
      ) : <p className="muted small">{j.note || t("No location signal yet.")}</p>}
      {j.signals?.length > 0 && (
        <ul className="reasons small">{j.signals.map((s, i) => <li key={i}>{s.detail}{s.kind !== "place" && <> — <code>{s.value}</code></>}</li>)}</ul>
      )}
      {j.district && <p className="muted small">{j.note}</p>}
    </section>
  );
}

export function EvidencePanel({ pid, info }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [showLog, setShowLog] = useState(false);
  const { me } = useAuth();
  const pack = async () => {
    setBusy(true); setMsg("");
    try { const r = await api.evidencePack(pid); setMsg(t("Downloaded {name}. SHA-256 of the ZIP: {sha}", { name: r.name, sha: r.sha })); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const intact = info.evidence.every((f) => f.intact);
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Evidence")}</h2>
        {info.evidence.length > 0 && <span className={`chip ${intact ? "chip-ok" : "chip-td"}`}>{intact ? t("unchanged since capture") : t("a file has changed")}</span>}</div>
      {info.evidence.length ? (
        <div className="ev-files">{info.evidence.map((f) => (
          <div key={f.id} className="ev-file">
            <span className="id-kind">{t(f.kind)}</span>
            <div><b>{f.name}</b> <span className="muted small">{(f.size / 1024).toFixed(1)} KB · {t("captured {when} IST", { when: istTime(f.captured_at) })}</span>
              <code className="hash">{f.sha256}</code></div>
            {can(me, "IO") && <button className="icon-btn" title={t("Download")} onClick={() => api.evidenceFile(pid, f.id).catch((e) => setMsg(e.message))}><Icon name="download" size={16} /></button>}
          </div>
        ))}</div>
      ) : <p className="muted small">{t("Captured before evidence capture was added. The record hash is still below.")}</p>}
      {!info.screenshots?.screenshots && <p className="muted small">{t("Full-page screenshots are off:")} {info.screenshots?.error || t("install Playwright to turn them on")}</p>}
      {can(me, "IO") && (
        <div className="ev-actions">
          <button className="btn" disabled={busy} onClick={pack}><Icon name="download" /> {t("Evidence pack (ZIP)")}</button>
          <button className="linkish" onClick={() => setShowLog(!showLog)}>{t(showLog ? "Hide chain of custody ({n})" : "Show chain of custody ({n})", { n: info.custody?.length || 0 })}</button>
        </div>
      )}
      {msg && <p className="small note">{msg}</p>}
      {showLog && (
        <div className="tbl-wrap"><table className="tbl tbl-tight custody">
          <thead><tr><th>{t("When (IST)")}</th><th>{t("Who")}</th><th>{t("Action")}</th></tr></thead>
          <tbody>{info.custody.slice().reverse().map((r) => (
            <tr key={r.id}><td className="small">{istTime(r.at)}</td><td className="small">{r.username}</td><td className="small"><code>{r.action}</code></td></tr>
          ))}</tbody>
        </table></div>
      )}
    </section>
  );
}

const DRAFT_HELP = {
  takedown: "Notice under Section 79(3)(b) IT Act for the platform, to file on the Sahyog portal. Linked posts on the same platform are included.",
  preservation: "Asks the platform to preserve account records and logs for 180 days, ahead of a formal data request.",
  bank: "Request to the bank's nodal officer for KYC, statements and logs, with linked complaints for marking a lien.",
  bsa63: "Certificate for the captured records under Section 63(4) of the Bharatiya Sakshya Adhiniyam, with their SHA-256 hashes.",
};

export function DraftsPanel({ info, onOpen }) {
  const { t } = useT();
  if (!info.can_act) return null;
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Legal drafts")}</h2><span className="muted small">{t("English or Hindi · Word or PDF")}</span></div>
      <div className="drafts">
        {info.drafts.map((d) => (
          <button key={d.kind} className="draft-btn" disabled={d.kind === "bank" && !info.banks.length} onClick={() => onOpen(d.kind)}>
            <Icon name="doc" size={18} />
            <span><b>{t(d.label)}</b><small>{d.kind === "bank" && !info.banks.length ? t("No bank or UPI identifier in this post") : t(DRAFT_HELP[d.kind])}</small></span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function DraftEditor({ pid, kind, bank: bank0, label, onClose, onExported }) {
  const { t } = useT();
  const [lang, setLang] = useState("en");
  const [bank, setBank] = useState(bank0);
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    setData(null); setErr("");
    api.draft(pid, kind, lang, bank).then((d) => { setData(d); setText(d.text); }).catch((e) => setErr(e.message));
  }, [pid, kind, lang, bank]);
  const blanks = (text.match(/\[\[/g) || []).length;
  const exp = async (format) => {
    setBusy(format); setErr("");
    try { await api.exportDraft(pid, kind, { text, lang, format }); onExported?.(); } catch (e) { setErr(e.message); }
    setBusy("");
  };
  return (
    <Modal title={`${label} — ${caseId(pid)}`} onClose={onClose} wide>
      <div className="draft-bar">
        <div className="seg">
          <button className={`seg-btn${lang === "en" ? " on-indigo" : ""}`} onClick={() => setLang("en")}>{t("English")}</button>
          <button className={`seg-btn${lang === "hi" ? " on-indigo" : ""}`} onClick={() => setLang("hi")}>हिंदी</button>
        </div>
        {kind === "bank" && data?.banks?.length > 1 && (
          <select value={bank} onChange={(e) => setBank(e.target.value)} aria-label={t("Bank")}>
            {data.banks.map((b) => <option key={b.code} value={b.code}>{b.bank}</option>)}
          </select>
        )}
        <span className={`blanks${blanks ? "" : " ok"}`}>{blanks ? t("{n} fields to fill or confirm [[ … ]]", { n: blanks }) : t("No blanks left")}</span>
      </div>
      {err && <p className="err">{err}</p>}
      {data ? <textarea className="draft-text" value={text} onChange={(e) => setText(e.target.value)} spellCheck={lang === "en"} /> : <p className="muted">{t("Preparing the draft…")}</p>}
      <div className="draft-foot">
        <p className="muted small">{t("Edit the text here, then download. Every file is marked “DRAFT — to be reviewed and signed by the authorised officer”, and the export is recorded in the audit log. The legal references are a starting point; confirm them before sending.")}</p>
        <div className="draft-dl">
          <button className="btn" disabled={!data || !!busy} onClick={() => exp("docx")}><Icon name="download" /> {t("Word")}</button>
          <button className="btn btn-primary" disabled={!data || !!busy} onClick={() => exp("pdf")}><Icon name="pdf" /> PDF</button>
        </div>
      </div>
    </Modal>
  );
}

export function RepostBanner({ info }) {
  const { t } = useT();
  if (!info.repost_of) return null;
  return (
    <div className="banner warn case-banner"><Icon name="repeat" /> <span><T k="This came back after a takedown: it is linked to {case}, which was removed. Consider a notice against the account itself, not just the post." case={<Link to={`/case/${info.repost_of}`}>{caseId(info.repost_of)}</Link>} /></span></div>
  );
}
