"""
Ingest service: subscribe to POC/RTU card traffic on MQTT, run the Gibbs
downhole transform + diagnosis, and persist surface card + KPIs.

The transport here is MQTT, but the parse-then-store_card() core is transport
agnostic - a Modbus or OPC-UA poller would hand the same dict to handle().
"""
from __future__ import annotations
import os, sys, json, time
from datetime import datetime

import paho.mqtt.client as mqtt

sys.path.insert(0, "/app/common")
from db import connect, load_wells                    # noqa: E402
from store import store_card                          # noqa: E402

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
TOPIC     = os.getenv("MQTT_TOPIC", "srp/+/dynacard")

conn = connect()
wells = load_wells(conn)
print(f"[ingest] loaded {len(wells)} wells", flush=True)
_count = 0


def handle(payload: dict):
    global wells, _count
    wid = payload["well_id"]
    well = wells.get(wid)
    if well is None:                                  # new well registered live
        wells = load_wells(conn)
        well = wells.get(wid)
        if well is None:
            print(f"[ingest] unknown well {wid}, dropping", flush=True); return

    ts = datetime.fromisoformat(payload["ts"])
    with conn.cursor() as cur:
        m = store_card(cur, well, ts, payload["position"], payload["load"])
    _count += 1
    if _count % 20 == 0:
        print(f"[ingest] {_count} cards stored (last {wid}: {m.diagnosis}, "
              f"fill {m.fillage_pct}%)", flush=True)


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[ingest] connected to broker ({reason_code}), subscribing {TOPIC}",
          flush=True)
    client.subscribe(TOPIC, qos=1)


def on_message(client, userdata, msg):
    try:
        handle(json.loads(msg.payload))
    except Exception as e:                             # never die on one bad card
        print(f"[ingest] error on {msg.topic}: {e}", flush=True)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ingest")
    client.on_connect = on_connect
    client.on_message = on_message
    for _ in range(30):
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60); break
        except OSError:
            print("[ingest] waiting for MQTT broker...", flush=True); time.sleep(2)
    client.loop_forever()


if __name__ == "__main__":
    main()
