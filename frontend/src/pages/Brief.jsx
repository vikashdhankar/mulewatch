import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Icon } from "../components/ui";

export default function Brief() {
  const { t, lang: uiLang } = useT();
  const [lang, setLang] = useState(uiLang);
  const [hours, setHours] = useState(24);
  const [sched, setSched] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);
  const [district, setDistrict] = useState("");
  const [districts, setDistricts] = useState([]);
  useEffect(() => { api.districts().then((d) => setDistricts(d.districts.map((x) => x.name))).catch(() => {}); }, []);
  useEffect(() => { api.briefSchedule().then(setSched).catch(() => {}); }, []);
  const url = api.briefUrl(lang, hours, district) + `&n=${n}`;
  const send = async () => {
    setBusy(true);
    try { setMsg((await api.briefSend(lang)).message); } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  return (
    <div>
      <div className="page-head">
        <h1>{t("Daily brief")}</h1>
        <p>{t("One page for the SP or SHO: new and critical cases, cases linked to complaints, rings, takedown status, how fast each platform removed content, and where cases are.")}</p>
      </div>
      <div className="filters">
        <div className="seg">
          <button className={`seg-btn${lang === "en" ? " on-indigo" : ""}`} onClick={() => setLang("en")}>{t("English")}</button>
          <button className={`seg-btn${lang === "hi" ? " on-indigo" : ""}`} onClick={() => setLang("hi")}>हिंदी</button>
        </div>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label={t("Period")}>
          <option value={24}>{t("Last 24 hours")}</option>
          <option value={168}>{t("Last 7 days")}</option>
          <option value={720}>{t("Last 30 days")}</option>
        </select>
        <select value={district} onChange={(e) => setDistrict(e.target.value)} aria-label={t("District")}>
          <option value="">{t("All districts")}</option>
          {districts.map((d) => <option key={d} value={d}>{t(d)}</option>)}
        </select>
        <button className="btn" onClick={() => setN(n + 1)}><Icon name="refresh" /> {t("Refresh")}</button>
        <a className="btn" href={url} target="_blank" rel="noreferrer"><Icon name="pdf" /> {t("Open PDF")}</a>
        <button className="btn btn-primary" onClick={send} disabled={busy}>{t("Send on Telegram now")}</button>
      </div>
      {msg && <div className="note">{msg}</div>}
      {sched && (
        <p className="muted small">
          {t("Sent automatically every day at {time} IST in {lang}, for all districts.", { time: sched.time, lang: t(sched.lang === "hi" ? "Hindi" : "English") })}{" "}
          {!sched.bot ? t("Needs a Telegram bot (TELEGRAM_BOT_TOKEN in .env).") : sched.supervisor_chats ? t("Goes to {n} supervisors.", { n: sched.supervisor_chats })
            : <>{t("No supervisor has linked Telegram yet:")} <Link to="/profile">{t("My account")}</Link>.</>}{" "}
          {t("Change the time with DAILY_BRIEF_TIME in .env.")}
        </p>
      )}
      <iframe key={url} className="brief-frame" title={t("Daily brief")} src={url} />
    </div>
  );
}
