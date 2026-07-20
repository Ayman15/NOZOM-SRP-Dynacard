import { useEffect, useRef, useState, useMemo } from "react";

const API = "";  // same origin; nginx proxies /api -> api service

const DIAG = {
  full:             { c: "var(--ok)",    label: "Full pump" },
  fluid_pound:      { c: "var(--fault)", label: "Fluid pound" },
  gas_interference: { c: "var(--warn)",  label: "Gas interference" },
  gas_lock:         { c: "var(--fault)", label: "Gas lock" },
  tv_leak:          { c: "var(--fault)", label: "TV leak" },
  sv_leak:          { c: "var(--fault)", label: "SV leak" },
};
const diag = (d) => DIAG[d] || { c: "var(--ink-dim)", label: d || "—" };
const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString(undefined,
  { minimumFractionDigits: d, maximumFractionDigits: d }));

async function j(url) { const r = await fetch(url); if (!r.ok) throw 0; return r.json(); }

/* ---- oscilloscope card plot ---------------------------------------- */
function Scope({ card }) {
  const [sweep, setSweep] = useState(0);
  const raf = useRef();
  useEffect(() => {
    let i = 0;
    const tick = () => { i = (i + 1) % 200; setSweep(i); raf.current = requestAnimationFrame(tick); };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [card]);

  const W = 640, H = 460, pad = 46;
  const geom = useMemo(() => {
    if (!card) return null;
    const s = card.surface, d = card.downhole;
    const xs = s.position.concat(d.position), ys = s.load.concat(d.load);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const mx = (x1 - x0) * 0.08, my = (y1 - y0) * 0.10;
    const sx = (v) => pad + (v - (x0 - mx)) / ((x1 + mx) - (x0 - mx)) * (W - 2 * pad);
    const sy = (v) => H - pad - (v - (y0 - my)) / ((y1 + my) - (y0 - my)) * (H - 2 * pad);
    const path = (P, L) => P.map((p, i) => `${i ? "L" : "M"}${sx(p).toFixed(1)} ${sy(L[i]).toFixed(1)}`).join(" ") + "Z";
    return { sx, sy, x0, x1, y0, y1,
      surf: path(s.position, s.load), dh: path(d.position, d.load),
      sweepPt: [sx(s.position[sweep]), sy(s.load[sweep])] };
  }, [card, sweep]);

  if (!geom) return <svg className="scope" viewBox={`0 0 ${W} ${H}`} />;
  const gx = 8, gy = 6;
  return (
    <svg className="scope" viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="2.2" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {/* graticule */}
      {Array.from({ length: gx + 1 }, (_, i) => {
        const x = pad + i * (W - 2 * pad) / gx;
        return <line key={"x" + i} x1={x} y1={pad} x2={x} y2={H - pad} stroke="var(--grid)" strokeWidth="1" />;
      })}
      {Array.from({ length: gy + 1 }, (_, i) => {
        const y = pad + i * (H - 2 * pad) / gy;
        return <line key={"y" + i} x1={pad} y1={y} x2={W - pad} y2={y} stroke="var(--grid)" strokeWidth="1" />;
      })}
      {/* axis labels */}
      <text x={W / 2} y={H - 12} fill="var(--ink-dim)" fontSize="12"
        textAnchor="middle" fontFamily="var(--cond)" letterSpacing="2">
        POSITION  (in)</text>
      <text x={16} y={H / 2} fill="var(--ink-dim)" fontSize="12" textAnchor="middle"
        fontFamily="var(--cond)" letterSpacing="2" transform={`rotate(-90 16 ${H / 2})`}>
        LOAD  (lb)</text>
      {/* traces */}
      <path d={geom.dh}   fill="none" stroke="var(--downhole)" strokeWidth="1.8"
        opacity="0.95" filter="url(#glow)" />
      <path d={geom.surf} fill="none" stroke="var(--surface)"  strokeWidth="1.8"
        filter="url(#glow)" />
      {/* sweep marker on the measured trace */}
      <circle cx={geom.sweepPt[0]} cy={geom.sweepPt[1]} r="4.5"
        fill="var(--surface)" filter="url(#glow)" />
    </svg>
  );
}

/* ---- fillage scrub timeline ---------------------------------------- */
function Timeline({ index, selectedTs, onPick }) {
  const W = 900, H = 96, pad = 8;
  if (!index || index.length < 2)
    return <div className="tl-hint">No history in range.</div>;
  const t = index.map((r) => new Date(r.ts).getTime());
  const t0 = t[0], t1 = t[t.length - 1];
  const sx = (v) => pad + (v - t0) / (t1 - t0 || 1) * (W - 2 * pad);
  const sy = (v) => H - 10 - (v / 100) * (H - 24);
  const line = index.map((r, i) => `${i ? "L" : "M"}${sx(t[i]).toFixed(1)} ${sy(r.fillage_pct).toFixed(1)}`).join(" ");
  const selX = selectedTs ? sx(new Date(selectedTs).getTime()) : null;

  const pick = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width * W;
    const tv = t0 + (px - pad) / (W - 2 * pad) * (t1 - t0);
    let best = 0, bd = Infinity;
    t.forEach((tt, i) => { const dd = Math.abs(tt - tv); if (dd < bd) { bd = dd; best = i; } });
    onPick(index[best].ts);
  };

  return (
    <svg className="tl-svg" viewBox={`0 0 ${W} ${H}`} onClick={pick}
      onMouseDown={(e) => e.buttons && pick(e)} onMouseMove={(e) => e.buttons && pick(e)}>
      {[0, 50, 100].map((v) => (
        <g key={v}>
          <line x1={pad} y1={sy(v)} x2={W - pad} y2={sy(v)} stroke="var(--grid)" />
          <text x={W - pad} y={sy(v) - 3} fill="var(--ink-dim)" fontSize="10"
            textAnchor="end">{v}%</text>
        </g>
      ))}
      {index.map((r, i) => (
        <circle key={i} cx={sx(t[i])} cy={sy(r.fillage_pct)} r="2"
          fill={diag(r.diagnosis).c} opacity="0.85" />
      ))}
      <path d={line} fill="none" stroke="var(--surface)" strokeWidth="1.4" opacity="0.6" />
      {selX != null && (
        <g>
          <line className="tl-cursor" x1={selX} y1={4} x2={selX} y2={H - 4}
            stroke="var(--surface)" strokeWidth="1.5" />
          <polygon className="tl-cursor" points={`${selX - 5},2 ${selX + 5},2 ${selX},9`} />
        </g>
      )}
    </svg>
  );
}

/* ---- app ----------------------------------------------------------- */
export default function App() {
  const [fleet, setFleet] = useState(null);
  const [sel, setSel] = useState(null);
  const [index, setIndex] = useState([]);
  const [ts, setTs] = useState(null);
  const [card, setCard] = useState(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const load = () => j(`${API}/api/fleet`).then(setFleet).catch(() => {});
    load(); const iv = setInterval(load, 15000); return () => clearInterval(iv);
  }, []);
  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(iv);
  }, []);
  useEffect(() => {
    if (!sel && fleet?.wells?.length) setSel(fleet.wells[0].well_id);
  }, [fleet, sel]);
  useEffect(() => {
    if (!sel) return;
    j(`${API}/api/wells/${sel}/cards?hours=72&limit=1000`).then((ix) => {
      setIndex(ix); setTs(ix.length ? ix[ix.length - 1].ts : null);
    }).catch(() => setIndex([]));
  }, [sel]);
  useEffect(() => {
    if (!sel) return;
    const u = ts ? `${API}/api/wells/${sel}/card?ts=${encodeURIComponent(ts)}`
                 : `${API}/api/wells/${sel}/card`;
    j(u).then(setCard).catch(() => setCard(null));
  }, [sel, ts]);

  const m = card?.metrics;
  const dg = diag(m?.diagnosis);

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">SRP <b>Dynacard</b> Monitor</div>
        <div className="tagline">rod-pump surveillance · downhole diagnostics</div>
        <div className="clock">{now.toISOString().replace("T", "  ").slice(0, 19)} UTC</div>
      </div>

      <div className="layout">
        <aside className="wells">
          <div className="wells-head">
            <span>Field</span>
            <span className="count">{fleet ? fleet.wells.length : "—"} wells</span>
          </div>
          {fleet?.wells?.map((w) => (
            <div key={w.well_id} className={"well-row" + (w.well_id === sel ? " sel" : "")}
              onClick={() => setSel(w.well_id)}>
              <span className="dot" style={{ background: diag(w.diagnosis).c,
                boxShadow: `0 0 8px ${diag(w.diagnosis).c}` }} />
              <span>
                <div className="well-id">{w.well_id}</div>
                <div className="well-sub">{w.field} · {diag(w.diagnosis).label}</div>
              </span>
              <span className="well-fill">{fmt(w.fillage_pct, 0)}%</span>
            </div>
          ))}
        </aside>

        <main className="stage">
          {!card ? <div className="empty">Select a well</div> : (
            <>
              <div className="stage-head">
                <div className="well-title">{card.well_id}</div>
                <div className="badge" style={{ color: dg.c, borderColor: dg.c }}>
                  <span className="dot" style={{ background: dg.c }} />
                  {dg.label}
                  <span className="conf">{fmt((m.confidence || 0) * 100, 0)}% conf</span>
                </div>
                <div className="well-meta">
                  {fmt(card.spm, 1)} SPM · {fmt(card.stroke_in, 0)}" stroke ·
                  {"  "}{new Date(card.ts).toISOString().slice(0, 16).replace("T", " ")} UTC
                </div>
              </div>

              <div className="grid2">
                <div className="panel">
                  <div className="panel-h">
                    <span>Dynamometer card</span>
                    <span className="legend">
                      <span><i style={{ background: "var(--surface)" }} />surface · measured</span>
                      <span><i style={{ background: "var(--downhole)" }} />downhole · Gibbs</span>
                    </span>
                  </div>
                  <div className="scope-wrap"><Scope card={card} /></div>
                </div>

                <div className="panel">
                  <div className="panel-h"><span>Card metrics</span></div>
                  <div className="scope-wrap">
                    <div className="readouts">
                      <div className="ro cyan"><div className="k">Fillage</div>
                        <div className="v">{fmt(m.fillage_pct, 1)}<small>%</small></div></div>
                      <div className="ro cyan"><div className="k">Pump displacement</div>
                        <div className="v">{fmt(m.pump_disp_bpd, 1)}<small>bbl/d</small></div></div>
                      <div className="ro amber"><div className="k">Peak rod load</div>
                        <div className="v">{fmt(m.pprl)}<small>lb</small></div></div>
                      <div className="ro amber"><div className="k">Min rod load</div>
                        <div className="v">{fmt(m.mprl)}<small>lb</small></div></div>
                      <div className="ro"><div className="k">Fluid load Fo</div>
                        <div className="v">{fmt(m.fluid_load)}<small>lb</small></div></div>
                      <div className="ro"><div className="k">Card area</div>
                        <div className="v">{fmt(m.card_area / 1000, 1)}<small>k·in·lb</small></div></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="panel timeline">
                <div className="panel-h">
                  <span>Fillage history · 72 h</span>
                  <span>drag to scrub</span>
                </div>
                <Timeline index={index} selectedTs={ts} onPick={setTs} />
                <div className="tl-hint">
                  Each dot is one card, coloured by diagnosis. Click or drag to inspect any stroke.
                </div>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
