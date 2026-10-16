import L from "leaflet";
import { tr, useT } from "../i18n";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, caseId } from "../api";
import { Empty } from "../components/ui";
import { useLive } from "../live";

const BOUNDS = [[23.0, 69.4], [30.3, 78.3]];      // Rajasthan
const INDIA = [[6.5, 68.0], [37.2, 97.5]];
const geo = (f) => fetch(`/geo/${f}`).then((r) => r.json());

function heat(n, max) {
  if (!n) return "#fbfaf6";
  const k = Math.sqrt(n / max);
  return k > 0.75 ? "#e8606e" : k > 0.5 ? "#f08a5d" : k > 0.25 ? "#f6b07a" : "#fbd5b0";
}

export default function MapPage() {
  const { t } = useT();
  const { version } = useLive();
  const [d, setD] = useState(null);
  const [sel, setSel] = useState(null);
  const [shapes, setShapes] = useState(null);
  const box = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const distLayer = useRef(null);

  useEffect(() => { api.districts().then(setD).catch(() => {}); }, [version]);
  useEffect(() => {
    Promise.all([geo("india-boundary.json"), geo("india-states.json"), geo("rajasthan-districts-2011.json")])
      .then(([india, states, dists]) => setShapes({ india, states, dists })).catch(() => {});
  }, []);

  useEffect(() => {
    if (!box.current || map.current) return;
    // No online tiles: India is drawn from the Survey of India boundary files bundled with the app,
    // so the map shows India's boundaries as published by the Government of India and works offline.
    const m = L.map(box.current, { zoomSnap: 0.25, minZoom: 4, maxZoom: 10, maxBounds: [[2, 60], [40, 102]],
      attributionControl: true }).fitBounds(BOUNDS);
    m.attributionControl.setPrefix(false);
    m.attributionControl.addAttribution("Boundaries: Survey of India · Districts: Census 2011");
    const View = L.Control.extend({
      onAdd() {
        const div = L.DomUtil.create("div", "leaflet-bar map-views");
        div.innerHTML = `<a href="#" data-v="raj">${tr("Rajasthan")}</a><a href="#" data-v="ind">${tr("India")}</a>`;
        L.DomEvent.on(div, "click", (e) => {
          L.DomEvent.preventDefault(e);
          const v = e.target.getAttribute("data-v");
          if (v) m.flyToBounds(v === "ind" ? INDIA : BOUNDS, { duration: 0.6 });
        });
        return div;
      },
    });
    new View({ position: "topright" }).addTo(m);
    // drawing order: India fill < district shading < state lines < district dots
    [["basePane", 350], ["linePane", 420], ["dotPane", 430]].forEach(([n, z]) => {
      const p = m.createPane(n);
      p.style.zIndex = z;
      if (n === "linePane") p.style.pointerEvents = "none";
    });
    distLayer.current = L.layerGroup().addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => { m.remove(); map.current = null; };
  }, []);

  // base: India, states, Rajasthan
  useEffect(() => {
    if (!shapes || !map.current) return;
    const m = map.current;
    const base = L.layerGroup().addTo(m);
    L.geoJSON(shapes.india, { pane: "basePane", interactive: false, style: { color: "#5f6780", weight: 1.3, fillColor: "#f4f1e8", fillOpacity: 1 } }).addTo(base);
    L.geoJSON(shapes.states, {
      pane: "linePane", interactive: false,
      style: (f) => f.properties.name === "Rajasthan"
        ? { color: "#2b3a9f", weight: 2.2, fill: false }
        : { color: "#b4b9c7", weight: 0.8, fill: false },
    }).addTo(base);
    return () => { base.remove(); };
  }, [shapes]);

  useEffect(() => {
    if (!d || !layer.current) return;
    layer.current.clearLayers();
    distLayer.current.clearLayers();
    const max = Math.max(1, ...d.districts.map((x) => x.cases));
    const byName = Object.fromEntries(d.districts.map((x) => [x.name, x]));
    if (shapes) {
      L.geoJSON(shapes.dists, {
        style: (f) => {
          const x = byName[f.properties.name];
          return { color: "#8f97b3", weight: 0.8, fillColor: heat(x?.cases || 0, max), fillOpacity: 0.9 };
        },
        onEachFeature: (f, l) => {
          const x = byName[f.properties.name];
          if (!x) return;
          l.bindTooltip(`${tr(x.name)} — ${tr(x.cases === 1 ? "{n} case" : "{n} cases", { n: x.cases })}`, { sticky: true });
          l.on("click", () => setSel(x));
        },
      }).addTo(distLayer.current);
    }
    d.districts.forEach((x) => {
      const r = x.cases ? 7 + 20 * Math.sqrt(x.cases / max) : 3;
      const c = L.circleMarker([x.lat, x.lon], {
        pane: "dotPane", radius: r, weight: x.cases ? 2 : 1,
        color: x.critical ? "#a5162a" : x.cases ? "#c25a00" : "#6f7899",
        fillColor: x.critical ? "#d7263d" : x.cases ? "#ea7317" : "#ffffff", fillOpacity: x.cases ? 0.6 : 0.9,
      });
      c.bindTooltip(`${tr(x.name)} (${x.name}) — ${tr(x.cases === 1 ? "{n} case" : "{n} cases", { n: x.cases })}`);
      c.on("click", () => setSel(x));
      c.addTo(layer.current);
    });
  }, [d, shapes]);

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
      <p className="muted small map-note">{t("India's external and state boundaries are drawn from Survey of India records, with no online map tiles, so the map works offline. District lines are the 33 districts of Census 2011; districts created since (Balotra, Beawar, Deeg, Didwana-Kuchaman, Khairthal-Tijara, Kotputli-Behror, Phalodi, Salumbar) are shown by their headquarters. Darker shading means more High/Critical cases.")}</p>
    </div>
  );
}
