import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, caseId, timeAgo } from "../api";
import { RiskBadge } from "./ui";
import { useLive } from "../live";

export function useBot(extra = 0) {
  const { version } = useLive();
  const [bot, setBot] = useState(null);
  useEffect(() => {
    const load = () => api.bot().then(setBot).catch(() => setBot(null));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [version, extra]);
  return bot;
}

export function Qr({ value, size = 148 }) {
  const [svg, setSvg] = useState("");
  useEffect(() => {
    if (value) QRCode.toString(value, { type: "svg", margin: 1, errorCorrectionLevel: "M", color: { dark: "#121a36", light: "#ffffff" } })
      .then(setSvg).catch(() => setSvg(""));
  }, [value]);
  return svg ? <div className="qr" style={{ width: size, height: size }} role="img" aria-label={`QR code for ${value}`}
    dangerouslySetInnerHTML={{ __html: svg }} /> : null;
}

/** Compact card for the dashboard: scan to report. */
export function BotCard() {
  const bot = useBot();
  if (!bot?.enabled) return null;
  return (
    <section className="panel bot-card">
      <div className="panel-head"><h2>Citizen reports</h2><Link to="/sources#bot" className="more">Details</Link></div>
      {bot.link ? (
        <div className="bot-row">
          <Qr value={bot.link} size={112} />
          <div>
            <p>Scan to report a suspicious ad on Telegram</p>
            <a href={bot.link} target="_blank" rel="noreferrer" className="bot-handle">@{bot.username}</a>
            <p className="muted small">{bot.reports} report{bot.reports === 1 ? "" : "s"} from {bot.reporters} {bot.reporters === 1 ? "person" : "people"}</p>
          </div>
        </div>
      ) : <p className="muted small">Connecting to Telegram… {bot.last_error}</p>}
    </section>
  );
}

/** Full panel for the Monitored sources page. */
export function BotPanel() {
  const [tick, setTick] = useState(0);
  const bot = useBot(tick);
  if (!bot) return null;
  if (!bot.enabled) {
    return (
      <section className="panel" id="bot">
        <div className="panel-head"><h2>Citizen reporting bot</h2><span className="muted small">Off</span></div>
        <p className="small">Let anyone forward a suspicious message, link or screenshot to a Telegram bot and get an instant verdict. Create a bot with <b>@BotFather</b>, put its token in <code>.env</code> as <code>REPORT_BOT_TOKEN</code>, and restart.</p>
      </section>
    );
  }
  return (
    <section className="panel" id="bot">
      <div className="panel-head">
        <h2>Citizen reporting bot</h2>
        <span className={`small ${bot.running ? "ok-text" : "err"}`}>{bot.running ? "Online" : `Not connected${bot.last_error ? `: ${bot.last_error}` : ""}`}</span>
      </div>
      <div className="bot-wrap">
        <div className="bot-qr">
          {bot.link && <Qr value={bot.link} size={150} />}
          {bot.link && <a href={bot.link} target="_blank" rel="noreferrer" className="bot-handle">@{bot.username}</a>}
        </div>
        <div className="bot-body">
          <dl className="sys">
            <dt>Reports received</dt><dd>{bot.reports}</dd>
            <dt>People reporting</dt><dd>{bot.reporters}</dd>
            <dt>Cases opened</dt><dd>{bot.cases} <Link to="/cases?source=citizen" className="small">view</Link></dd>
            <dt>Last report</dt><dd>{bot.last_report_at ? timeAgo(bot.last_report_at) : "none yet"}</dd>
            <dt>Phone alerts</dt>
            <dd>{bot.alerts_linked
              ? <>On, sent to <b>{bot.alerts_to || "linked chat"}</b>{" "}
                  {bot.alerts_to !== "TELEGRAM_CHAT_ID in .env" &&
                    bot.alert_code && <button className="linkish" onClick={async () => { await api.unlinkAlerts(); setTick((x) => x + 1); }}>turn off</button>}</>
              : bot.alert_code
                ? <>Off. To get Critical alerts on the unit's phone, send <code className="code-big">/alerts {bot.alert_code}</code> to {bot.username ? <a href={bot.link} target="_blank" rel="noreferrer">@{bot.username}</a> : "the bot"}.</>
                : <>Off. A supervisor can link the unit's alert chat. For your own case alerts, use <Link to="/profile">My account</Link>.</>}
            </dd>
          </dl>
          <p className="muted small">Reporters get a verdict with safety advice in English and Hindi, and a message when investigators confirm, dismiss or take down what they reported. Their identity isn't shown here.</p>
        </div>
      </div>
      {bot.recent?.length > 0 && (
        <div className="bot-recent">
          {bot.recent.map((r, i) => (
            <Link key={i} to={`/case/${r.post_id}`} className="alert-row">
              <RiskBadge level={r.risk_level} score={r.risk_score} />
              <div><strong>{caseId(r.post_id)}</strong> <span className="muted small">{timeAgo(r.at)} · {r.origin}</span>
                <div className="small">{r.excerpt}</div></div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
