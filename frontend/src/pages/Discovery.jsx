import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, can, caseId, istTime, timeAgo } from "../api";
import { useAuth } from "../auth";
import { T, useT } from "../i18n";
import { Empty, Icon, RiskBadge } from "../components/ui";

const SITES = [["", "Whole web"], ["t.me", "Telegram"], ["instagram.com", "Instagram"], ["facebook.com", "Facebook"],
  ["youtube.com", "YouTube"], ["x.com", "X"], ["olx.in", "OLX"], ["sharechat.com", "ShareChat"], ["quora.com", "Quora"],
  ["reddit.com", "Reddit"]];
const SITE_NAME = Object.fromEntries(SITES);

function Engine({ st, onRun, me }) {
  const { t } = useT();
  const pct = st.budget ? Math.min(100, Math.round((st.used_today / st.budget) * 100)) : 0;
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{t("Search engine")}</h2>
        <span className={`chip ${st.provider && !st.demo ? "chip-ok" : ""}`}>{st.provider ? (st.demo ? t("Demo mode") : st.provider_name) : t("Not set up")}</span>
      </div>
      {st.demo || !st.provider ? (
        <div className="note small">
          <p><b>{st.demo ? t("Running in demo mode: searches go to the local Charcha forum, not the internet.") : t("No search provider is set up.")}</b></p>
          <p>{t("To search the whole internet, put one of these in .env and restart:")}</p>
          <ul className="disc-keys">
            <li><code>BRAVE_API_KEY</code> — {t("Brave Search API (independent index, pay per search)")}</li>
            <li><code>SERPER_API_KEY</code> — {t("Serper.dev (Google results, pay per search)")}</li>
            <li><code>GOOGLE_CSE_KEY</code> + <code>GOOGLE_CSE_CX</code> — {t("Google Programmable Search (existing customers only)")}</li>
            <li><code>SEARXNG_URL</code> — {t("your own SearXNG server (free)")}</li>
          </ul>
        </div>
      ) : (
        <div className="bulk-prog">
          <div className="bar"><i style={{ width: `${pct}%` }} /></div>
          <span className="small">{t("{a} of {b} searches used today", { a: st.used_today, b: st.budget })}</span>
        </div>
      )}
      <dl className="disc-facts">
        <dt>{t("Schedule")}</dt><dd>{t("Every {m} min, up to {b} searches each time", { m: st.interval_min, b: st.batch })}</dd>
        <dt>{t("Searches in rotation")}</dt><dd>{st.queries}{st.rotation_days != null && !st.demo && <> · {t("all repeated about every {d} days", { d: st.rotation_days })}</>}</dd>
        <dt>{t("Results from the last")}</dt><dd>{t({ week: "week", month: "month", year: "year" }[st.freshness] || "any time")}</dd>
        <dt>{t("Next run")}</dt><dd>{st.busy ? t("running now…") : st.next_run ? istTime(st.next_run) + " IST" : "—"}</dd>
      </dl>
      {st.last_error && <p className="err small">{st.last_error}</p>}
      {can(me, "IO") && <button className="btn btn-primary" disabled={st.busy || !st.provider} onClick={onRun}><Icon name="search" /> {st.busy ? t("Searching…") : t("Search now")}</button>}
    </section>
  );
}

function Runs({ runs }) {
  const { t } = useT();
  return (
    <section className="panel">
      <div className="panel-head"><h2>{t("Recent runs")}</h2></div>
      {runs.length ? (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>{t("When (IST)")}</th><th>{t("Searches")}</th><th>{t("Results")}</th><th>{t("New")}</th><th>{t("Flagged")}</th></tr></thead>
          <tbody>{runs.map((r) => (
            <tr key={r.id} title={r.error || ""}>
              <td>{istTime(r.started_at)}<div className="small muted">{r.trigger === "schedule" ? t("scheduled") : r.trigger}{!r.done && ` · ${t("running now…")}`}</div></td>
              <td>{r.queries}</td><td>{r.results}</td><td>{r.new_hits}</td>
              <td>{r.flagged ? <b className="err">{r.flagged}</b> : 0}{r.error && <span className="chip" title={r.error}>!</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <p className="muted small">{t("No runs yet.")}</p>}
    </section>
  );
}

function Districts({ rows, sel, onSel }) {
  const { t } = useT();
  return (
    <div className="disc-grid">
      {rows.map((d) => (
        <button key={d.district || "-"} className={`disc-dist${sel === (d.district || "-") ? " on" : ""}${d.flagged ? " hot" : ""}`}
          onClick={() => onSel(sel === (d.district || "-") ? "" : (d.district || "-"))}>
          <span className="dd-name">{d.district ? t(d.district) : t("Statewide")}</span>
          <strong>{d.flagged}</strong>
          <span className="small">{t("flagged · {n} found", { n: d.hits })}</span>
          <span className="small muted">{d.last ? t("last flagged {ago}", { ago: timeAgo(d.last) }) : t("{n} searches run", { n: d.searched })}</span>
        </button>
      ))}
    </div>
  );
}

function Findings({ district, platforms }) {
  const { t } = useT();
  const [show, setShow] = useState("flagged");
  const [platform, setPlatform] = useState("");
  const [data, setData] = useState(null);
  useEffect(() => {
    let stop = false;
    const load = () => api.discoveryHits({ show, platform, district }).then((d) => { if (!stop) setData(d); }).catch(() => {});
    load();
    const tm = setInterval(load, 8000);
    return () => { stop = true; clearInterval(tm); };
  }, [show, platform, district]);
  return (
    <>
      <div className="filters">
        <div className="seg">
          {[["flagged", t("High and Critical")], ["cases", t("All opened")], ["all", t("Everything found")], ["skipped", t("Not opened")]].map(([k, l]) => (
            <button key={k} className={`seg-btn${show === k ? " on-indigo" : ""}`} onClick={() => setShow(k)}>{l}</button>
          ))}
        </div>
        <select value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label={t("Platform")}>
          <option value="">{t("All platforms")}</option>
          {platforms.map(([p, n]) => <option key={p} value={p}>{p} ({n})</option>)}
        </select>
        {data && <span className="small muted">{t("{n} results", { n: data.total })}</span>}
      </div>
      <section className="panel">
        {!data ? <p className="muted">{t("Loading…")}</p> : data.items.length ? (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>{t("Found")}</th><th>{t("Search result")}</th><th>{t("Result")}</th><th>{t("Case")}</th></tr></thead>
            <tbody>{data.items.map((h) => (
              <tr key={h.id}>
                <td className="nowrap">{timeAgo(h.found_at)}<div className="small muted">{h.district ? t(h.district) : t("Statewide")}</div><div className="small muted">{h.platform}</div></td>
                <td className="bulk-url">
                  <a href={h.url} target="_blank" rel="noreferrer noopener"><b>{h.title || h.url}</b></a>
                  {h.snippet && <div className="small">{h.snippet}</div>}
                  <div className="small muted">{h.url}{h.seen > 1 && ` · ${t("seen in {n} searches", { n: h.seen })}`}</div>
                </td>
                <td>
                  {h.post ? <RiskBadge level={h.post.risk_level} score={h.post.risk_score} />
                    : <span className="chip">{t({ skipped: "not opened", existing: "already a case", error: "couldn't open", new: "waiting" }[h.status] || h.status)}</span>}
                  {h.how === "snippet" && <div><span className="chip chip-warn" title={t("The page needs a login, so the case was built from the search result. Open the original and verify.")}>{t("from search result only")}</span></div>}
                  {h.post?.complaint_count > 0 && <div><span className="chip chip-comp">{t(h.post.complaint_count === 1 ? "{n} complaint" : "{n} complaints", { n: h.post.complaint_count })}</span></div>}
                  <div className="small muted">{t("first look {s}", { s: Math.round(h.triage) })}</div>
                </td>
                <td>{h.post && <><Link to={`/case/${h.post.id}`}><code>{caseId(h.post.id)}</code></Link><div className="small muted">{t(h.post.category)}</div></>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        ) : <Empty title={show === "flagged" ? t("Nothing High or Critical found yet") : t("Nothing here yet")}>{t("Results appear here after each search run.")}</Empty>}
      </section>
    </>
  );
}

function Channels({ me }) {
  const { t } = useT();
  const [rows, setRows] = useState([]);
  const load = useCallback(() => api.discoveryChannels().then(setRows).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  const act = async (id, action) => { await api.discoveryChannel(id, action); load(); };
  return (
    <section className="panel">
      <p className="small">{t("Telegram channels and groups named in what the search found. Monitoring one adds it to Monitored sources, so every new post in it is checked within seconds.")}</p>
      {rows.length ? (
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>{t("Channel")}</th><th>{t("Mentions")}</th><th>{t("Districts")}</th><th>{t("First seen")}</th><th>{t("Status")}</th><th /></tr></thead>
          <tbody>{rows.map((c) => (
            <tr key={c.id}>
              <td><a href={`https://t.me/s/${c.handle}`} target="_blank" rel="noreferrer noopener"><code>@{c.handle}</code></a>
                {c.example_url && <div className="small muted bulk-url">{c.example_url}</div>}</td>
              <td>{c.mentions}</td>
              <td className="small">{c.districts.map((d) => t(d)).join(", ") || "—"}</td>
              <td className="small">{timeAgo(c.first_seen)}</td>
              <td><span className={`chip ${c.status === "monitored" ? "chip-ok" : ""}`}>{t({ suggested: "suggested", monitored: "monitored", ignored: "ignored" }[c.status])}</span>{c.by && <div className="small muted">{c.by}</div>}</td>
              <td className="nowrap">{can(me, "IO") && (c.status === "suggested" ? <>
                <button className="btn btn-primary btn-sm" onClick={() => act(c.id, "monitor")}>{t("Monitor")}</button>{" "}
                <button className="btn btn-sm" onClick={() => act(c.id, "ignore")}>{t("Ignore")}</button></>
                : c.status === "ignored" && <button className="linkish" onClick={() => act(c.id, "reset")}>{t("Undo")}</button>)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <Empty title={t("No channels found yet")}>{t("Channels appear here when a search result or a page mentions a t.me link.")}</Empty>}
    </section>
  );
}

function Searches({ me, districts }) {
  const { t } = useT();
  const [rows, setRows] = useState([]);
  const [district, setDistrict] = useState("");
  const [custom, setCustom] = useState(false);
  const [text, setText] = useState("");
  const [nd, setNd] = useState("");
  const [site, setSite] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api.discoveryQueries({ district, kind: custom ? "custom" : "" }).then(setRows).catch(() => {}), [district, custom]);
  useEffect(() => { load(); }, [load]);
  const add = async (e) => {
    e.preventDefault(); setMsg("");
    try { const r = await api.discoveryAddQuery(text, nd, site); setMsg(t("Added: {q}", { q: r.text })); setText(""); load(); }
    catch (x) { setMsg(x.message); }
  };
  return (
    <>
      {can(me, "IO") && (
        <section className="panel">
          <div className="panel-head"><h2>{t("Add a search")}</h2></div>
          <p className="small">{t("Add wording you have seen in local ads or complaints. Your searches run before the generated ones.")}</p>
          <form className="import-row disc-add" onSubmit={add}>
            <label>{t("Words to search for")}<input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("e.g. khata chahiye gaming withdrawal")} required /></label>
            <label>{t("District")}<select value={nd} onChange={(e) => setNd(e.target.value)}>
              <option value="">{t("Statewide")}</option>{districts.map((d) => <option key={d} value={d}>{t(d)}</option>)}</select></label>
            <label>{t("Platform")}<select value={site} onChange={(e) => setSite(e.target.value)}>
              {SITES.map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}</select></label>
            <button className="btn btn-primary">{t("Add")}</button>
          </form>
          {msg && <p className="small note">{msg}</p>}
        </section>
      )}
      <div className="filters">
        <select value={district} onChange={(e) => setDistrict(e.target.value)} aria-label={t("District")}>
          <option value="">{t("All districts")}</option><option value="-">{t("Statewide")}</option>
          {districts.map((d) => <option key={d} value={d}>{t(d)}</option>)}
        </select>
        <label className="toggle small"><input type="checkbox" checked={custom} onChange={(e) => setCustom(e.target.checked)} /> {t("Only searches added by officers")}</label>
        <span className="small muted">{t("Showing {n}", { n: rows.length })}</span>
      </div>
      <section className="panel">
        <div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>{t("Search")}</th><th>{t("Platform")}</th><th>{t("Runs")}</th><th>{t("New")}</th><th>{t("Flagged")}</th><th>{t("Last run")}</th><th>{t("On")}</th></tr></thead>
          <tbody>{rows.map((q) => (
            <tr key={q.id} className={q.enabled ? "" : "muted"}>
              <td><code className="disc-q">{q.text}</code>{q.kind === "custom" && <div className="small muted">{t("added by {who}", { who: q.by })}</div>}
                {q.last_error && <div className="small err">{q.last_error}</div>}</td>
              <td className="small">{t(SITE_NAME[q.site] || q.site || "Whole web")}</td>
              <td>{q.runs}</td><td>{q.new_hits}</td><td>{q.flagged ? <b className="err">{q.flagged}</b> : 0}</td>
              <td className="small">{q.last_run ? timeAgo(q.last_run) : t("not yet")}</td>
              <td><input type="checkbox" checked={q.enabled} disabled={!can(me, "IO")} aria-label={t("On")}
                onChange={async (e) => { await api.discoveryToggleQuery(q.id, e.target.checked); load(); }} /></td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
    </>
  );
}

export default function Discovery() {
  const { t } = useT();
  const { me } = useAuth();
  const [st, setSt] = useState(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("found");
  const [district, setDistrict] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api.discovery().then(setSt).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); const tm = setInterval(load, 6000); return () => clearInterval(tm); }, [load]);
  if (err && !st) return <Empty title={t("Internet discovery isn't available")}>{err}</Empty>;
  if (!st) return <p className="muted">{t("Loading…")}</p>;
  const run = async () => { const r = await api.discoveryRun(); setMsg(t(r.message)); load(); };
  return (
    <div>
      <div className="page-head">
        <h1>{t("Internet discovery")}</h1>
        <p>{t("Searches the public internet on a schedule for ads selling or renting bank accounts and cards, district by district: Telegram channels, Instagram, Facebook pages and groups, YouTube, X, OLX, forums and websites. Promising results are opened and scored like any other post, and High/Critical ones become cases with the usual alerts.")}</p>
      </div>
      {msg && <div className="note">{msg}</div>}
      <div className="two-col">
        <Engine st={st} me={me} onRun={run} />
        <Runs runs={st.runs} />
      </div>
      <div className="panel-head disc-head"><h2>{t("Target districts")}</h2>
        <span className="small muted">{t("{a} found · {b} opened · {c} High/Critical", { a: st.totals.hits, b: st.totals.cases, c: st.totals.flagged })}</span></div>
      <Districts rows={st.districts} sel={district} onSel={(d) => { setDistrict(d); setTab("found"); }} />
      <div className="filters">
        <div className="seg">
          {[["found", t("Findings")], ["channels", t("Telegram channels")], ["searches", t("Searches")]].map(([k, l]) => (
            <button key={k} className={`seg-btn${tab === k ? " on-indigo" : ""}`} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        {district && tab === "found" && <button className="chip" onClick={() => setDistrict("")}>{district === "-" ? t("Statewide") : t(district)} ✕</button>}
      </div>
      {tab === "found" && <Findings district={district} platforms={st.platforms} />}
      {tab === "channels" && <Channels me={me} />}
      {tab === "searches" && <Searches me={me} districts={st.districts.map((d) => d.district).filter(Boolean)} />}
      <p className="muted small">
        <T k="Only content that search engines have indexed publicly is reached; nothing behind a login is opened. Cases built from a search result alone are marked {mark}: open the original and verify before acting." mark={<span className="chip chip-warn">{t("from search result only")}</span>} />
      </p>
    </div>
  );
}
