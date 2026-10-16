import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, caseId } from "../api";
import { Empty } from "../components/ui";
import { useLive } from "../live";

const BOUNDS = [[23.0, 69.4], [30.3, 78.3]];      // Rajasthan

export default function MapPage() {
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
        <h1>District map</h1>
        <p>High and Critical cases by suggested district, from the account's IFSC branch and places named in the ad. Approximate: use it to route cases, not as proof of location.</p>
      </div>
      <div className="net-wrap">
        <section className="panel map-panel"><div ref={box} className="map" role="img" aria-label="Map of Rajasthan districts with case counts" /></section>
        <section className="panel net-side">
          {sel ? (
            <>
              <button className="linkish small" onClick={() => setSel(null)}>All districts</button>
              <h3>{sel.name} <span className="muted">{sel.hi}</span></h3>
              <p className="small">{sel.cases} case{sel.cases === 1 ? "" : "s"} · {sel.critical} critical · {sel.open} open · {sel.complaints} complaint link{sel.complaints === 1 ? "" : "s"}</p>
              <p className="small">Route to: <b>Cyber Police Station, {sel.name}</b></p>
              {sel.top.map((t) => <Link key={t.id} to={`/case/${t.id}`} className="mini-post"><code>{caseId(t.id)}</code><span>{t.category} · {Math.round(t.risk_score)}</span></Link>)}
              <Link className="more" to={`/cases?district=${encodeURIComponent(sel.name)}&level=Critical,High`}>All {sel.name} cases</Link>
            </>
          ) : (
            <>
              <h4>Districts with cases</h4>
              {ranked.length ? ranked.map((x) => (
                <button key={x.name} className="dist-row" onClick={() => setSel(x)}>
                  <span>{x.name}</span><div className="bar"><i style={{ width: `${(x.cases / ranked[0].cases) * 100}%` }} /></div><b>{x.cases}</b>
                </button>
              )) : <Empty title="No located cases yet">Cases get a district when the post names a place or gives an IFSC.</Empty>}
              {d?.unplaced > 0 && <p className="muted small">{d.unplaced} High/Critical case{d.unplaced === 1 ? " has" : "s have"} no location signal.</p>}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
