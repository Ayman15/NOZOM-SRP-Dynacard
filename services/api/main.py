"""
Read API for the card-review UI and any external client.

Surface cards are stored; the downhole card is computed on the fly with the
Gibbs transform (microseconds) so storage stays lean and the raw table stays
canonical.
"""
from __future__ import annotations
import os, sys
from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, "/app/common")
from dynacard import gibbs_downhole, diagnose         # noqa: E402
from db import connect, load_wells                    # noqa: E402

app = FastAPI(title="SRP Dynacard API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

conn = connect()
WELLS = load_wells(conn)


def _wells_refresh():
    global WELLS
    WELLS = load_wells(conn)


@app.get("/api/health")
def health():
    return {"ok": True, "wells": len(WELLS)}


@app.get("/api/wells")
def wells():
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM wells ORDER BY well_id")
        return cur.fetchall()


@app.get("/api/fleet")
def fleet():
    """Latest status for every well - powers the overview grid."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM well_latest ORDER BY well_id")
        rows = cur.fetchall()
        cur.execute("""SELECT diagnosis, count(*) AS n
                       FROM well_latest GROUP BY diagnosis""")
        summary = {r["diagnosis"]: r["n"] for r in cur.fetchall()}
    return {"wells": rows, "summary": summary}


@app.get("/api/wells/{well_id}/cards")
def card_index(well_id: str, hours: int = Query(24, ge=1, le=8760),
               limit: int = Query(500, ge=1, le=5000)):
    """Timestamps + headline KPI for the scrubber timeline."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ts, fillage_pct, pump_disp_bpd, diagnosis, confidence
            FROM card_metrics
            WHERE well_id = %s AND ts >= %s
            ORDER BY ts DESC LIMIT %s""", (well_id, since, limit))
        return list(reversed(cur.fetchall()))


@app.get("/api/wells/{well_id}/card")
def card(well_id: str, ts: str | None = None):
    """One card: stored surface loop + on-demand downhole loop + KPIs."""
    well = WELLS.get(well_id)
    if well is None:
        _wells_refresh(); well = WELLS.get(well_id)
    if well is None:
        raise HTTPException(404, "unknown well")

    with conn.cursor() as cur:
        if ts:
            cur.execute("""SELECT * FROM dynacards_raw
                           WHERE well_id=%s AND ts=%s""", (well_id, ts))
        else:
            cur.execute("""SELECT * FROM dynacards_raw
                           WHERE well_id=%s ORDER BY ts DESC LIMIT 1""",
                        (well_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "no card")

    pos = np.asarray(row["position"], float)
    load = np.asarray(row["load"], float)
    dh_pos, dh_load = gibbs_downhole(pos, load, well)
    m = diagnose(pos, load, dh_pos, dh_load, well)

    return {
        "well_id": well_id, "ts": row["ts"],
        "spm": row["spm"], "stroke_in": row["stroke_in"],
        "surface":  {"position": pos.tolist(),   "load": load.tolist()},
        "downhole": {"position": dh_pos.tolist(), "load": dh_load.tolist()},
        "metrics": {
            "pprl": m.pprl, "mprl": m.mprl, "card_area": m.card_area,
            "fluid_load": m.fluid_load, "fillage_pct": m.fillage_pct,
            "pump_disp_bpd": m.pump_disp_bpd,
            "diagnosis": m.diagnosis, "confidence": m.confidence,
        },
    }


@app.get("/api/wells/{well_id}/metrics")
def metrics(well_id: str, hours: int = Query(72, ge=1, le=8760)):
    """KPI time series for the trend strip."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ts, fillage_pct, pump_disp_bpd, pprl, mprl,
                   card_area, fluid_load, diagnosis
            FROM card_metrics
            WHERE well_id=%s AND ts>=%s
            ORDER BY ts""", (well_id, since))
        return cur.fetchall()
