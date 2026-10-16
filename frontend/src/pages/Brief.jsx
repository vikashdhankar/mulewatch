import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/ui";

export default function Brief() {
  const [lang, setLang] = useState("en");
  const [hours, setHours] = useState(24);
  const [sched, setSched] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => { api.briefSchedule().then(setSched).catch(() => {}); }, []);
  const url = `/api/brief.pdf?lang=${lang}&hours=${hours}&n=${n}`;
  const send = async () => {
    setBusy(true);
    try { setMsg((await api.briefSend(lang)).message); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  return (
    <div>
      <div className="page-head">
        <h1>Daily brief</h1>
        <p>One page for the SP or SHO: new and critical cases, cases linked to complaints, rings, takedown status, how fast each platform removed content, and where cases are.</p>
      </div>
      <div className="filters">
        <div className="seg">
          <button className={`seg-btn${lang === "en" ? " on-indigo" : ""}`} onClick={() => setLang("en")}>English</button>
          <button className={`seg-btn${lang === "hi" ? " on-indigo" : ""}`} onClick={() => setLang("hi")}>हिंदी</button>
        </div>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Period">
          <option value={24}>Last 24 hours</option>
          <option value={168}>Last 7 days</option>
          <option value={720}>Last 30 days</option>
        </select>
        <button className="btn" onClick={() => setN(n + 1)}><Icon name="refresh" /> Refresh</button>
        <a className="btn" href={url} target="_blank" rel="noreferrer"><Icon name="pdf" /> Open PDF</a>
        <button className="btn btn-primary" onClick={send} disabled={busy}>Send on Telegram now</button>
      </div>
      {msg && <div className="note">{msg}</div>}
      {sched && (
        <p className="muted small">
          Sent automatically every day at {sched.time} IST in {sched.lang === "hi" ? "Hindi" : "English"}
          {!sched.bot ? " once a Telegram bot is set up (TELEGRAM_BOT_TOKEN in .env)" : sched.supervisor_chats ? ` to ${sched.supervisor_chats} supervisor${sched.supervisor_chats === 1 ? "" : "s"}`
            : <> — no supervisor has linked Telegram yet (<Link to="/profile">My account</Link>)</>}.
          Change the time with DAILY_BRIEF_TIME in .env.
        </p>
      )}
      <iframe key={url} className="brief-frame" title="Daily brief" src={url} />
    </div>
  );
}
