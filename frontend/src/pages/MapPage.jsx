import L from "leaflet";
import { useT } from "../i18n";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, caseId } from "../api";
import { Empty } from "../components/ui";
import { useLive } from "../live";

const BOUNDS = [[23.0, 69.4], [30.3, 78.3]];      // Rajasthan

export default function MapPage() {
  const { t } = useT();
  const { version } = useLive();
  const [d, setD] = useState(null);
  const [sel, setSel] = useState(null);
  const box = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);

  useEffect(() => { api.districts().then(setD).catch(() => {}); }, [version]);

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = L.map(box.current, { zoomSnap: 0.25, attributionControl: true }).fitBounds(BOUNDS);
    // tiles need internet; without it the markers still show on a plain background
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12, attribution: "© OpenStreetMap contributors",
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    if (!d || !layer.current) return;
    layer.current.clearLayers();
    const max = Math.max(1, ...d.districts.map((x) => x.cases));
    d.districts.forEach((x) => {
      const r = x.cases ? 9 + 26 * Math.sqrt(x.cases / max) : 4;
      const c = L.circleMarker([x.lat, x.lon], {
        radius: r, weight: x.cases ? 2 : 1,
        color: x.critical ? "#a5162a" : x.cases ? "#c25a00" : "#8a93b8",
        fillColor: x.critical ? "#d7263d" : x.cases ? "#ea7317" : "#c9d0ea", fillOpacity: x.cases ? 0.55 : 0.4,
      });
      c.bindTooltip(`${x.name} (${x.hi}) — ${x.cases} case${x.cases === 1 ? "" : "s"}`);
      c.on("click", () => setSel(x));
      c.addTo(layer.current);
    });
  }, [d]);

  const ranked = d ? d.districts.filter((x) => x.cases).sort((a, b) => b.cases - a.cases) : [];
  return (
    <div>
      <div className="page-head">
        <h1>{t("District map")}</h1>
        <p>{t("High and Critical cases by suggested district, from the account's IFSC branch and places named in the ad. Approximate: use it to route cases, not as proof of location.")}</p>
      </div>
      <div className="net-wrap">
        <section className="panel map-panel"><div ref={box} className="map" role="img" aria-label={t("Map of Rajasthan districts with case counts")} /></section>
        <section className="panel net-side">
          {sel ? (
            <>
              <button className="linkish small" onClick={() => setSel(null)}>{t("All districts")}</button>
              <h3>{t(sel.name)} <span className="muted">{sel.name}</span></h3>
              <p className="small">{t("{a} cases · {b} critical · {c} open · {d} complaint links", { a: sel.cases, b: sel.critical, c: sel.open, d: sel.complaints })}</p>
              <p className="small">{t("Route to:")} <b>{t("Cyber Police Station, {d}", { d: t(sel.name) })}</b></p>
              {sel.top.map((x) => <Link key={x.id} to={`/case/${x.id}`} className="mini-post"><code>{caseId(x.id)}</code><span>{t(x.category)} · {Math.round(x.risk_score)}</span></Link>)}
              <Link className="more" to={`/cases?district=${encodeURIComponent(sel.name)}&level=Critical,High`}>{t("All cases in {d}", { d: t(sel.name) })}</Link>
            </>
          ) : (
            <>
              <h4>{t("Districts with cases")}</h4>
              {ranked.length ? ranked.map((x) => (
                <button key={x.name} className="dist-row" onClick={() => setSel(x)}>
                  <span>{t(x.name)}</span><div className="bar"><i style={{ width: `${(x.cases / ranked[0].cases) * 100}%` }} /></div><b>{x.cases}</b>
                </button>
              )) : <Empty title={t("No located cases yet")}>{t("Cases get a district when the post names a place or gives an IFSC.")}</Empty>}
              {d?.unplaced > 0 && <p className="muted small">{t("{n} High/Critical cases have no district signal.", { n: d.unplaced })}</p>}
              {d?.circles?.length > 0 && (
                <>
                  <h4>{t("Mobile numbers by telecom circle")}</h4>
                  {d.circles.map(([c, n]) => (
                    <div key={c} className="dist-row static"><span>{t(c)}</span><div className="bar"><i style={{ width: `${(n / d.circles[0][1]) * 100}%` }} /></div><b>{n}</b></div>
                  ))}
                  <p className="muted small">{t("Where each number's series was first allotted. Ported numbers can be used anywhere, so this is a hint, not a location.")}</p>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
