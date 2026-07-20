"""Shared database helpers used by the ingest service and the simulator."""
from __future__ import annotations
import os, time
import psycopg
from psycopg.rows import dict_row
from dynacard import Well


def dsn() -> str:
    return (
        f"host={os.getenv('PGHOST', 'postgres')} "
        f"port={os.getenv('PGPORT', '5432')} "
        f"dbname={os.getenv('PGDATABASE', 'srp')} "
        f"user={os.getenv('PGUSER', 'srp')} "
        f"password={os.getenv('PGPASSWORD', 'srp')}"
    )


def connect(retries: int = 30, delay: float = 2.0) -> psycopg.Connection:
    """Connect, waiting for Postgres to accept connections on cold start."""
    last = None
    for _ in range(retries):
        try:
            return psycopg.connect(dsn(), autocommit=True, row_factory=dict_row)
        except psycopg.OperationalError as e:      # db not ready yet
            last = e
            time.sleep(delay)
    raise last


def load_wells(conn) -> dict[str, Well]:
    """Read the well register into dynacard.Well objects, keyed by well_id."""
    wells: dict[str, Well] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM wells ORDER BY well_id")
        for r in cur.fetchall():
            wells[r["well_id"]] = Well(
                well_id=r["well_id"], stroke_in=r["stroke_in"], spm=r["spm"],
                depth_ft=r["depth_ft"], rod_area_in2=r["rod_area_in2"],
                rod_wt_lbft=r["rod_wt_lbft"], buoyancy=r["buoyancy"],
                plunger_in=r["plunger_in"], net_lift_psi=r["net_lift_psi"],
                unit_asym=r["unit_asym"], damping=r["damping"],
            )
    return wells
