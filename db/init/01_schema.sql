-- =====================================================================
--  SRP Dynacard platform - schema
--  One card = one row.  The 200 (position, load) samples live in arrays,
--  never as 200 separate rows.  Heavy loops and slim KPIs are split into
--  two hypertables so trending/alerting never touches the raw payload.
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------
--  Well register: rod-string + pump geometry, the source of truth the
--  simulator and the ingest service both read to run the Gibbs transform.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wells (
    well_id       text PRIMARY KEY,
    name          text NOT NULL,
    field         text NOT NULL,
    stroke_in     real NOT NULL,
    spm           real NOT NULL,
    depth_ft      real NOT NULL,
    rod_area_in2  real NOT NULL DEFAULT 0.601,
    rod_wt_lbft   real NOT NULL DEFAULT 1.63,
    buoyancy      real NOT NULL DEFAULT 0.87,
    plunger_in    real NOT NULL DEFAULT 1.5,
    net_lift_psi  real NOT NULL DEFAULT 3000,
    unit_asym     real NOT NULL DEFAULT 0.22,
    damping       real NOT NULL DEFAULT 0.13,
    lat           double precision,
    lon           double precision,
    installed_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
--  Raw SURFACE cards.  Downhole cards are derived on demand (Gibbs is
--  microseconds) so we never pay to store them.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dynacards_raw (
    well_id    text        NOT NULL,
    ts         timestamptz NOT NULL,
    spm        real,
    stroke_in  real,
    position   real[]      NOT NULL,   -- 200 samples, inches
    load       real[]      NOT NULL,   -- 200 samples, pounds
    PRIMARY KEY (well_id, ts)
);
SELECT create_hypertable('dynacards_raw', 'ts',
                         chunk_time_interval => interval '1 day',
                         if_not_exists => TRUE);

-- ---------------------------------------------------------------------
--  Slim per-card KPIs + diagnosis.  Everything trended/alerted lives here.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS card_metrics (
    well_id        text        NOT NULL,
    ts             timestamptz NOT NULL,
    spm            real,
    stroke_in      real,
    pprl           real,        -- peak polished-rod load, lb
    mprl           real,        -- minimum polished-rod load, lb
    card_area      real,        -- downhole loop area (work/stroke)
    fluid_load     real,        -- estimated Fo, lb
    fillage_pct    real,
    pump_disp_bpd  real,
    diagnosis      text,
    confidence     real,
    PRIMARY KEY (well_id, ts)
);
SELECT create_hypertable('card_metrics', 'ts',
                         chunk_time_interval => interval '1 day',
                         if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS card_metrics_diag_idx
    ON card_metrics (diagnosis, ts DESC);

-- ---------------------------------------------------------------------
--  Compression: columnar, segmented by well.  Both hypertables compress
--  chunks older than 7 days (raw cards typically 85-92% smaller).
-- ---------------------------------------------------------------------
ALTER TABLE dynacards_raw SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'well_id',
    timescaledb.compress_orderby   = 'ts DESC'
);
ALTER TABLE card_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'well_id',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('dynacards_raw', interval '7 days',  if_not_exists => TRUE);
SELECT add_compression_policy('card_metrics',  interval '7 days',  if_not_exists => TRUE);

-- ---------------------------------------------------------------------
--  Retention: the 1-year requirement, enforced declaratively.  Old chunks
--  are dropped whole (instant, no VACUUM churn).
-- ---------------------------------------------------------------------
SELECT add_retention_policy('dynacards_raw', interval '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('card_metrics',  interval '400 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------
--  Continuous aggregate: hourly KPI rollup that powers fast fleet trends
--  and long-range dashboards without scanning every card.
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS card_metrics_hourly
WITH (timescaledb.continuous) AS
SELECT well_id,
       time_bucket('1 hour', ts)          AS bucket,
       count(*)                            AS n_cards,
       avg(fillage_pct)                    AS avg_fillage,
       min(fillage_pct)                    AS min_fillage,
       avg(pump_disp_bpd)                  AS avg_disp_bpd,
       avg(pprl)                           AS avg_pprl,
       avg(mprl)                           AS avg_mprl,
       mode() WITHIN GROUP (ORDER BY diagnosis) AS dominant_diag
FROM card_metrics
GROUP BY well_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy('card_metrics_hourly',
    start_offset      => interval '3 hours',
    end_offset        => interval '1 hour',
    schedule_interval => interval '30 minutes',
    if_not_exists     => TRUE);

-- Latest card per well: the fleet overview reads this constantly.
CREATE VIEW well_latest AS
SELECT DISTINCT ON (m.well_id)
       m.well_id, w.name, w.field, m.ts,
       m.fillage_pct, m.pump_disp_bpd, m.pprl, m.mprl,
       m.diagnosis, m.confidence
FROM card_metrics m
JOIN wells w USING (well_id)
ORDER BY m.well_id, m.ts DESC;
