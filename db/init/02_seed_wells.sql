-- =====================================================================
--  Seed 20 wells with deterministic, physically-plausible parameters.
--  This table is the source of truth; the simulator and ingest service
--  both read it, so there is no config drift between them.
-- =====================================================================
SELECT setseed(0.42);

INSERT INTO wells (well_id, name, field, stroke_in, spm, depth_ft,
                   rod_area_in2, rod_wt_lbft, buoyancy, plunger_in,
                   net_lift_psi, unit_asym, damping, lat, lon)
SELECT
    'W-' || lpad(g::text, 3, '0')                              AS well_id,
    (ARRAY['Permian','Bakken','Eagle Ford','Midland'])[1 + (g % 4)]
        || ' ' || lpad(g::text, 3, '0')                       AS name,
    (ARRAY['Permian','Bakken','Eagle Ford','Midland'])[1 + (g % 4)] AS field,
    (ARRAY[100,120,144,168])[1 + (floor(random()*4))::int]    AS stroke_in,
    round((5 + random()*6)::numeric, 1)                       AS spm,
    round((4000 + random()*4000)::numeric, 0)                 AS depth_ft,
    0.601, 1.63, 0.87, 1.5,
    round((2200 + random()*1600)::numeric, 0)                 AS net_lift_psi,
    round((0.15 + random()*0.15)::numeric, 3)                 AS unit_asym,
    round((0.09 + random()*0.10)::numeric, 3)                 AS damping,
    31.9 + random()*1.5                                       AS lat,
    -102.3 - random()*1.5                                     AS lon
FROM generate_series(1, 20) AS g
ON CONFLICT (well_id) DO NOTHING;
