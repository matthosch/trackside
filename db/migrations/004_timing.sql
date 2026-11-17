-- Stage 2: timing archives. raw -> staging -> marts, plus data-quality results.
-- Raw files themselves live on private storage, never in the database or repo.

CREATE SCHEMA raw;
CREATE SCHEMA staging;
CREATE SCHEMA marts;
CREATE SCHEMA ops;

-- Every file the pipeline has discovered on a timing archive, and what became of it.
CREATE TABLE raw.timing_files (
    id            bigserial PRIMARY KEY,
    url           text NOT NULL UNIQUE,
    source        text NOT NULL,             -- 'imsa' | 'sro_america'
    season        integer NOT NULL,
    event_folder  text NOT NULL,
    circuit_id    text NOT NULL REFERENCES circuits (id),
    series_folder text NOT NULL,
    session_folder text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('laps', 'results')),
    discovered_at timestamptz NOT NULL DEFAULT now(),
    local_path    text,
    sha256        text,
    bytes         bigint,
    fetched_at    timestamptz,
    loaded_at     timestamptz,
    load_error    text
);

CREATE TABLE staging.sessions (
    id             bigserial PRIMARY KEY,
    source         text NOT NULL,
    season         integer NOT NULL,
    circuit_id     text NOT NULL REFERENCES circuits (id),
    event_folder   text NOT NULL,
    series_folder  text NOT NULL,
    session_folder text NOT NULL,
    session_name   text NOT NULL,
    session_type   text NOT NULL CHECK (session_type IN ('practice', 'qualifying', 'race', 'test', 'other')),
    starts_at      timestamp,                -- track-local time from the folder name
    UNIQUE (source, season, event_folder, series_folder, session_folder)
);

-- One row per car per session, from the results file.
CREATE TABLE staging.session_entries (
    session_id bigint NOT NULL REFERENCES staging.sessions (id) ON DELETE CASCADE,
    car_number text NOT NULL,
    class      text NOT NULL,
    team       text NOT NULL,
    vehicle    text NOT NULL,
    PRIMARY KEY (session_id, car_number)
);

CREATE TABLE staging.laps (
    session_id    bigint NOT NULL REFERENCES staging.sessions (id) ON DELETE CASCADE,
    car_number    text NOT NULL,
    lap_number    integer NOT NULL,
    driver_number integer,
    driver_name   text,
    lap_time_ms   integer,
    s1_ms         integer,
    s2_ms         integer,
    s3_ms         integer,
    in_pit        boolean NOT NULL,
    flag          text,
    class         text NOT NULL,
    team          text,
    manufacturer  text,
    PRIMARY KEY (session_id, car_number, lap_number)
);

-- Harmonises vehicle names across hosts and seasons ("Aston Martin Vantage AMR GT3 EVO"
-- and "Aston Martin Vantage GT3 Evo" are the same car). Lowest priority wins.
CREATE TABLE staging.car_model_patterns (
    pattern  text PRIMARY KEY,               -- ILIKE pattern on the raw vehicle name
    model    text NOT NULL,
    priority integer NOT NULL
);

INSERT INTO staging.car_model_patterns (pattern, model, priority) VALUES
    ('%Aston Martin Vantage%EVO%', 'Aston Martin Vantage GT3 Evo', 10),
    ('%Aston Martin Vantage%', 'Aston Martin Vantage GT3', 20),
    ('%Audi R8%', 'Audi R8 LMS GT3', 20),
    ('%BMW M4%EVO%', 'BMW M4 GT3 Evo', 10),
    ('%BMW M4%', 'BMW M4 GT3', 20),
    ('%Corvette%', 'Chevrolet Corvette Z06 GT3.R', 20),
    ('%Ferrari 296%', 'Ferrari 296 GT3', 20),
    ('%Ferrari 488%', 'Ferrari 488 GT3 Evo', 20),
    ('%Mustang%', 'Ford Mustang GT3', 20),
    ('%Lamborghini%Temerario%', 'Lamborghini Temerario GT3', 10),
    ('%Lamborghini%Hurac%EVO2%', 'Lamborghini Huracán GT3 Evo2', 10),
    ('%Lamborghini%Hurac%', 'Lamborghini Huracán GT3', 20),
    ('%Lexus%RC%', 'Lexus RC F GT3', 20),
    ('%Acura%NSX%', 'Acura NSX GT3 Evo22', 20),
    ('%McLaren 720S%', 'McLaren 720S GT3 Evo', 20),
    ('%McLaren%Artura%', 'McLaren Artura GT3', 20),
    ('%Mercedes%AMG%', 'Mercedes-AMG GT3', 20),
    ('%Porsche%992%EVO%', 'Porsche 911 GT3 R (992) Evo', 10),
    ('%Porsche%911%R%EVO%', 'Porsche 911 GT3 R (992) Evo', 10),
    ('%Porsche%992%', 'Porsche 911 GT3 R (992)', 20),
    ('%Porsche%911%GT3%R%', 'Porsche 911 GT3 R (992)', 30),
    ('%Ford GT%', 'Ford GT', 40);

CREATE TABLE ops.dq_results (
    id         bigserial PRIMARY KEY,
    run_id     text NOT NULL,
    pipeline   text NOT NULL,
    check_name text NOT NULL,
    status     text NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
    value      double precision NOT NULL,
    warn_above double precision,
    fail_above double precision,
    detail     text,
    checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX dq_results_latest ON ops.dq_results (pipeline, check_name, checked_at DESC);
