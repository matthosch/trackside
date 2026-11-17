-- Core tables for stage 1: calendar and synthetic stays.

CREATE TABLE series (
    id           text PRIMARY KEY,
    name         text NOT NULL,
    calendar_url text NOT NULL
);

-- Curated dimension. Coordinates are approximate circuit centres.
CREATE TABLE circuits (
    id       text PRIMARY KEY,
    name     text NOT NULL,
    aliases  text[] NOT NULL DEFAULT '{}',
    locality text NOT NULL,
    country  text NOT NULL,
    lat      double precision NOT NULL,
    lon      double precision NOT NULL
);

CREATE TABLE events (
    id              bigserial PRIMARY KEY,
    series_id       text NOT NULL REFERENCES series (id),
    season          integer NOT NULL,
    round           integer,
    source_event_id text NOT NULL,
    slug            text NOT NULL,
    venue_name      text NOT NULL,
    -- NULL when the venue did not match a known circuit; a data-quality signal.
    circuit_id      text REFERENCES circuits (id),
    start_date      date NOT NULL,
    end_date        date NOT NULL,
    source_url      text NOT NULL,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (series_id, season, source_event_id)
);

-- Synthetic listings. Nothing here is a real property.
CREATE TABLE stays (
    id             text PRIMARY KEY,
    circuit_id     text NOT NULL REFERENCES circuits (id),
    title          text NOT NULL,
    kind           text NOT NULL,
    sleeps         integer NOT NULL,
    distance_km    numeric(5, 1) NOT NULL,
    bearing_deg    integer NOT NULL,
    base_price_usd integer NOT NULL
);

CREATE TABLE stay_price_snapshots (
    stay_id           text NOT NULL REFERENCES stays (id),
    event_id          bigint NOT NULL REFERENCES events (id),
    snapshot_date     date NOT NULL,
    nightly_price_usd integer NOT NULL,
    available         boolean NOT NULL,
    PRIMARY KEY (stay_id, event_id, snapshot_date)
);

CREATE INDEX stay_price_snapshots_event_date ON stay_price_snapshots (event_id, snapshot_date);
