"""
The one place a card becomes rows.  Both the live ingest path and the
simulator's history backfill call store_card(), so the transform + diagnosis
+ write logic exists exactly once.
"""
from __future__ import annotations
import numpy as np
from dynacard import Well, gibbs_downhole, diagnose

RAW_SQL = """
INSERT INTO dynacards_raw (well_id, ts, spm, stroke_in, position, load)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (well_id, ts) DO NOTHING
"""

MET_SQL = """
INSERT INTO card_metrics (well_id, ts, spm, stroke_in, pprl, mprl,
        card_area, fluid_load, fillage_pct, pump_disp_bpd, diagnosis, confidence)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (well_id, ts) DO UPDATE SET
    fillage_pct = EXCLUDED.fillage_pct,
    pump_disp_bpd = EXCLUDED.pump_disp_bpd,
    diagnosis = EXCLUDED.diagnosis,
    confidence = EXCLUDED.confidence
"""


def store_card(cur, well: Well, ts, position, load):
    """Persist one surface card + its derived KPIs.  Idempotent on (well, ts)."""
    pos = np.asarray(position, dtype=float)
    ld = np.asarray(load, dtype=float)

    dh_pos, dh_load = gibbs_downhole(pos, ld, well)
    m = diagnose(pos, ld, dh_pos, dh_load, well)

    cur.execute(RAW_SQL, (well.well_id, ts, well.spm, well.stroke_in,
                          pos.tolist(), ld.tolist()))
    cur.execute(MET_SQL, (well.well_id, ts, well.spm, well.stroke_in,
                          m.pprl, m.mprl, m.card_area, m.fluid_load,
                          m.fillage_pct, m.pump_disp_bpd,
                          m.diagnosis, m.confidence))
    return m
