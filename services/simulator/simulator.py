"""
Dynacard simulator for a 20-well field.

  * backfill : rapidly writes N hours of history straight to the database so
               dashboards have trends the moment the stack comes up.
  * live     : publishes one fresh surface card per well every few seconds to
               MQTT (topic srp/<well_id>/dynacard); the ingest service consumes
               them exactly as it would real POC/RTU traffic.

Each well is given a health scenario that drifts over time - healthy wells
breathe around full fillage, and several wells degrade into a fault partway
through the history window, so the fleet looks alive rather than static.
"""
from __future__ import annotations
import os, sys, json, time, math
from datetime import datetime, timedelta, timezone

import numpy as np
import paho.mqtt.client as mqtt

sys.path.insert(0, "/app/common")
from dynacard import simulate_surface_card                       # noqa: E402
from db import connect, load_wells                               # noqa: E402
from store import store_card                                     # noqa: E402

CYCLE_SECONDS   = int(os.getenv("CYCLE_SECONDS", "300"))         # real cadence
BACKFILL_HOURS  = int(os.getenv("BACKFILL_HOURS", "72"))
LIVE_INTERVAL   = float(os.getenv("LIVE_INTERVAL", "15"))        # accelerated
MQTT_HOST       = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT       = int(os.getenv("MQTT_PORT", "1883"))

# fault archetypes assigned across the fleet (index -> behaviour)
FAULTS = [
    "full", "full", "full", "full", "full", "full",
    "fluid_pound", "fluid_pound",
    "gas_interference", "gas_interference",
    "gas_lock", "tv_leak", "sv_leak",
    "degrade_pound", "degrade_pound",      # full -> fluid pound mid-window
    "degrade_gas",                          # full -> gas interference
    "full", "full", "sv_leak", "fluid_pound",
]


def scenario(idx: int, frac: float, rng: np.random.Generator):
    """Return (condition, fillage) for well `idx` at time-fraction `frac`
    through the window (0=oldest .. 1=now)."""
    kind = FAULTS[idx % len(FAULTS)]
    breathe = 0.03 * math.sin(2 * math.pi * (frac * 6 + idx))    # slow drift

    if kind == "full":
        return "full", float(np.clip(0.98 + breathe + rng.normal(0, .01), .9, 1))
    if kind == "fluid_pound":
        return "fluid_pound", float(np.clip(0.62 + breathe + rng.normal(0, .03), .4, .8))
    if kind == "gas_interference":
        return "gas_interference", float(np.clip(0.58 + breathe + rng.normal(0, .03), .4, .8))
    if kind == "gas_lock":
        return "gas_lock", float(np.clip(0.30 + rng.normal(0, .02), .2, .4))
    if kind == "tv_leak":
        return "tv_leak", 1.0
    if kind == "sv_leak":
        return "sv_leak", 1.0
    if kind == "degrade_pound":                    # healthy, then pumps off
        onset = 0.55
        if frac < onset:
            return "full", float(np.clip(0.97 + breathe, .9, 1))
        sev = (frac - onset) / (1 - onset)
        return "fluid_pound", float(np.clip(0.85 - 0.35 * sev + rng.normal(0, .02), .4, .9))
    if kind == "degrade_gas":
        onset = 0.65
        if frac < onset:
            return "full", float(np.clip(0.97 + breathe, .9, 1))
        sev = (frac - onset) / (1 - onset)
        return "gas_interference", float(np.clip(0.85 - 0.3 * sev, .45, .9))
    return "full", 1.0


def backfill(conn, wells):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(hours=BACKFILL_HOURS)
    n_steps = int(BACKFILL_HOURS * 3600 / CYCLE_SECONDS)
    print(f"[sim] backfilling {n_steps} cycles x {len(wells)} wells "
          f"({BACKFILL_HOURS}h history)...", flush=True)

    rng = np.random.default_rng(7)
    written = 0
    with conn.cursor() as cur:
        for s in range(n_steps):
            ts = start + timedelta(seconds=s * CYCLE_SECONDS)
            frac = s / max(1, n_steps - 1)
            for i, (wid, well) in enumerate(wells.items()):
                cond, fill = scenario(i, frac, rng)
                pos, load = simulate_surface_card(well, cond, fillage=fill)
                store_card(cur, well, ts, pos, load)
                written += 1
            if s % 50 == 0:
                print(f"[sim]   {s}/{n_steps} steps, {written} cards", flush=True)
    print(f"[sim] backfill complete: {written} cards", flush=True)


def live(wells):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulator")
    for _ in range(30):
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60); break
        except OSError:
            print("[sim] waiting for MQTT broker...", flush=True); time.sleep(2)
    client.loop_start()
    print(f"[sim] live streaming every {LIVE_INTERVAL}s -> mqtt://{MQTT_HOST}", flush=True)

    rng = np.random.default_rng()
    while True:
        ts = datetime.now(timezone.utc).replace(microsecond=0)
        frac = (ts.timestamp() % 86400) / 86400.0            # slow daily phase
        for i, (wid, well) in enumerate(wells.items()):
            cond, fill = scenario(i, frac, rng)
            pos, load = simulate_surface_card(well, cond, fillage=fill)
            payload = json.dumps({
                "well_id": wid, "ts": ts.isoformat(),
                "spm": well.spm, "stroke_in": well.stroke_in,
                "position": [round(float(x), 3) for x in pos],
                "load":     [round(float(x), 1) for x in load],
            })
            client.publish(f"srp/{wid}/dynacard", payload, qos=1)
        print(f"[sim] published {len(wells)} cards @ {ts.isoformat()}", flush=True)
        time.sleep(LIVE_INTERVAL)


def main():
    conn = connect()
    wells = load_wells(conn)
    if not wells:
        print("[sim] no wells found - is the seed loaded?", flush=True); return
    print(f"[sim] loaded {len(wells)} wells", flush=True)

    if os.getenv("DO_BACKFILL", "true").lower() == "true":
        backfill(conn, wells)
    if os.getenv("DO_LIVE", "true").lower() == "true":
        live(wells)


if __name__ == "__main__":
    main()
