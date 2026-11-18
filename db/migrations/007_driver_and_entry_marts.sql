-- Drivers and teams for the "what to watch" panel. Same lap rules as circuit_pace
-- (marts.lap_quality.valid), ranked within each class, because classes are
-- separate fights: GTD Pro vs GTD in IMSA, Pro vs Pro-Am vs Am in GT World
-- Challenge America. Refreshed by the timing pipeline after circuit_pace.

-- Every valid lap with who drove it, for which team, in which car.
CREATE VIEW marts.valid_laps AS
SELECT
    q.session_id, q.car_number, q.lap_number, q.lap_time_ms, q.class,
    q.source, q.season, q.circuit_id, q.session_type,
    l.driver_name, l.team,
    coalesce(vm.model, e.vehicle) AS model
FROM marts.lap_quality q
JOIN staging.laps l USING (session_id, car_number, lap_number)
LEFT JOIN staging.session_entries e ON e.session_id = q.session_id AND e.car_number = q.car_number
LEFT JOIN marts.vehicle_models vm ON vm.vehicle = e.vehicle
WHERE q.valid;

-- One row per driver per circuit, season, and source.
--   best_lap_ms:  the driver's fastest valid lap in any session
--   race_pace_ms: mean of the driver's own 10 fastest valid race laps (needs 5)
CREATE MATERIALIZED VIEW marts.driver_pace AS
WITH laps AS (
    SELECT * FROM marts.valid_laps WHERE driver_name IS NOT NULL AND driver_name <> ''
),
race AS (
    SELECT circuit_id, season, source, driver_name, round(avg(lap_time_ms))::integer AS race_pace_ms
    FROM (
        SELECT *, row_number() OVER (PARTITION BY circuit_id, season, source, driver_name
                                     ORDER BY lap_time_ms) AS rn
        FROM laps WHERE session_type = 'race'
    ) ranked
    WHERE rn <= 10
    GROUP BY circuit_id, season, source, driver_name
    HAVING count(*) >= 5
),
best AS (
    -- Class, car, and team come from the driver's best lap.
    SELECT DISTINCT ON (circuit_id, season, source, driver_name)
        circuit_id, season, source, driver_name, class, car_number, team, model,
        lap_time_ms AS best_lap_ms
    FROM laps
    ORDER BY circuit_id, season, source, driver_name, lap_time_ms
),
counts AS (
    SELECT circuit_id, season, source, driver_name, count(*) AS valid_laps
    FROM laps
    GROUP BY circuit_id, season, source, driver_name
)
SELECT
    b.*,
    c.valid_laps,
    r.race_pace_ms,
    r.race_pace_ms - min(r.race_pace_ms) OVER w AS race_gap_ms,
    b.best_lap_ms - min(b.best_lap_ms) OVER w AS best_gap_ms,
    rank() OVER (PARTITION BY b.circuit_id, b.season, b.source, b.class
                 ORDER BY r.race_pace_ms NULLS LAST, b.best_lap_ms) AS rank
FROM best b
JOIN counts c USING (circuit_id, season, source, driver_name)
LEFT JOIN race r USING (circuit_id, season, source, driver_name)
WINDOW w AS (PARTITION BY b.circuit_id, b.season, b.source, b.class);

CREATE UNIQUE INDEX driver_pace_key ON marts.driver_pace (circuit_id, season, source, driver_name);

-- One row per entry (car number) per circuit, season, and source: the team's view.
--   race_pace_ms: mean of the car's 10 fastest valid race laps, any driver (needs 5)
CREATE MATERIALIZED VIEW marts.entry_pace AS
WITH race AS (
    SELECT circuit_id, season, source, car_number, round(avg(lap_time_ms))::integer AS race_pace_ms
    FROM (
        SELECT *, row_number() OVER (PARTITION BY circuit_id, season, source, car_number
                                     ORDER BY lap_time_ms) AS rn
        FROM marts.valid_laps WHERE session_type = 'race'
    ) ranked
    WHERE rn <= 10
    GROUP BY circuit_id, season, source, car_number
    HAVING count(*) >= 5
),
best AS (
    SELECT DISTINCT ON (circuit_id, season, source, car_number)
        circuit_id, season, source, car_number, class, team, model,
        lap_time_ms AS best_lap_ms
    FROM marts.valid_laps
    ORDER BY circuit_id, season, source, car_number, lap_time_ms
),
crew AS (
    SELECT circuit_id, season, source, car_number,
           array_agg(DISTINCT driver_name ORDER BY driver_name) AS drivers
    FROM marts.valid_laps
    WHERE driver_name IS NOT NULL AND driver_name <> ''
    GROUP BY circuit_id, season, source, car_number
)
SELECT
    b.*,
    coalesce(crew.drivers, '{}') AS drivers,
    r.race_pace_ms,
    r.race_pace_ms - min(r.race_pace_ms) OVER w AS race_gap_ms,
    b.best_lap_ms - min(b.best_lap_ms) OVER w AS best_gap_ms,
    rank() OVER (PARTITION BY b.circuit_id, b.season, b.source, b.class
                 ORDER BY r.race_pace_ms NULLS LAST, b.best_lap_ms) AS rank
FROM best b
LEFT JOIN crew USING (circuit_id, season, source, car_number)
LEFT JOIN race r USING (circuit_id, season, source, car_number)
WINDOW w AS (PARTITION BY b.circuit_id, b.season, b.source, b.class);

CREATE UNIQUE INDEX entry_pace_key ON marts.entry_pace (circuit_id, season, source, car_number);
