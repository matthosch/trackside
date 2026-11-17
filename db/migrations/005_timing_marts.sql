-- Marts for the "what to watch" panel. Refreshed by the timing pipeline after each load.

-- Every lap with the reasons it is or is not usable for pace.
CREATE MATERIALIZED VIEW marts.lap_quality AS
WITH laps AS (
    SELECT
        l.*,
        s.source, s.season, s.circuit_id, s.session_type,
        lag(l.in_pit) OVER (PARTITION BY l.session_id, l.car_number ORDER BY l.lap_number) AS prev_in_pit
    FROM staging.laps l
    JOIN staging.sessions s ON s.id = l.session_id
),
session_median AS (
    SELECT session_id,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY lap_time_ms) AS median_ms
    FROM laps
    WHERE flag = 'GF' AND NOT in_pit AND lap_time_ms IS NOT NULL
    GROUP BY session_id
)
SELECT
    laps.session_id, laps.car_number, laps.lap_number, laps.lap_time_ms, laps.class,
    laps.source, laps.season, laps.circuit_id, laps.session_type,
    -- Faster than 85% of the session's typical green lap is not a real lap: bad
    -- timing data. (Very slow laps, such as red flags, are merely not valid.)
    (laps.lap_time_ms IS NULL OR laps.lap_time_ms < 0.85 * m.median_ms) AS implausible,
    (laps.flag = 'GF'
        AND NOT laps.in_pit
        AND NOT coalesce(laps.prev_in_pit, false)   -- out lap
        AND laps.lap_number > 1
        AND laps.lap_time_ms IS NOT NULL
        AND laps.lap_time_ms >= 0.85 * m.median_ms
        AND laps.lap_time_ms <= 600000) AS valid
FROM laps
LEFT JOIN session_median m ON m.session_id = laps.session_id;

CREATE INDEX lap_quality_session ON marts.lap_quality (session_id, car_number);

-- Raw vehicle name to harmonised model, for every vehicle seen.
CREATE VIEW marts.vehicle_models AS
SELECT DISTINCT ON (e.vehicle)
    e.vehicle,
    coalesce(p.model, e.vehicle) AS model,
    p.model IS NOT NULL AS mapped
FROM (SELECT DISTINCT vehicle FROM staging.session_entries) e
LEFT JOIN staging.car_model_patterns p ON e.vehicle ILIKE p.pattern
ORDER BY e.vehicle, p.priority NULLS LAST;

-- Pace by car model, per circuit, season, and source.
--   best_lap_ms:  fastest valid lap by any car of the model in any session
--   race_pace_ms: mean of the 10 fastest valid race laps, for the model's best car
CREATE MATERIALIZED VIEW marts.circuit_pace AS
WITH car_laps AS (
    SELECT q.*, vm.model
    FROM marts.lap_quality q
    JOIN staging.session_entries e ON e.session_id = q.session_id AND e.car_number = q.car_number
    JOIN marts.vehicle_models vm ON vm.vehicle = e.vehicle
    WHERE q.valid
),
race_top AS (
    SELECT session_id, car_number, model, circuit_id, season, source, lap_time_ms,
           row_number() OVER (PARTITION BY session_id, car_number ORDER BY lap_time_ms) AS rn
    FROM car_laps
    WHERE session_type = 'race'
),
race_pace AS (
    SELECT circuit_id, season, source, model, session_id, car_number,
           avg(lap_time_ms) AS pace_ms
    FROM race_top
    WHERE rn <= 10
    GROUP BY circuit_id, season, source, model, session_id, car_number
    HAVING count(*) >= 5
),
by_model AS (
    SELECT
        b.circuit_id, b.season, b.source, b.model,
        min(b.lap_time_ms) AS best_lap_ms,
        count(DISTINCT b.car_number) AS cars,
        count(*) AS valid_laps,
        (SELECT round(min(r.pace_ms))::integer FROM race_pace r
          WHERE r.circuit_id = b.circuit_id AND r.season = b.season
            AND r.source = b.source AND r.model = b.model) AS race_pace_ms
    FROM car_laps b
    GROUP BY b.circuit_id, b.season, b.source, b.model
)
SELECT
    *,
    race_pace_ms - min(race_pace_ms) OVER w AS race_gap_ms,
    best_lap_ms - min(best_lap_ms) OVER w AS best_gap_ms,
    rank() OVER (PARTITION BY circuit_id, season, source
                 ORDER BY race_pace_ms NULLS LAST, best_lap_ms) AS rank
FROM by_model
WINDOW w AS (PARTITION BY circuit_id, season, source);

CREATE UNIQUE INDEX circuit_pace_key ON marts.circuit_pace (circuit_id, season, source, model);
