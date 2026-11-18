package main

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("not found")

type Circuit struct {
	ID       string  `json:"id"`
	Name     string  `json:"name"`
	Locality string  `json:"locality"`
	Country  string  `json:"country"`
	Lat      float64 `json:"lat"`
	Lon      float64 `json:"lon"`
}

type Event struct {
	ID         int64    `json:"id"`
	SeriesID   string   `json:"series_id"`
	SeriesName string   `json:"series_name"`
	Season     int      `json:"season"`
	Round      *int     `json:"round"`
	Venue      string   `json:"venue"`
	Slug       string   `json:"slug"`
	StartDate  string   `json:"start_date"`
	EndDate    string   `json:"end_date"`
	SourceURL  string   `json:"source_url"`
	Circuit    *Circuit `json:"circuit"`
}

type Stay struct {
	ID              string          `json:"id"`
	Title           string          `json:"title"`
	Kind            string          `json:"kind"`
	Sleeps          int             `json:"sleeps"`
	DistanceKm      float64         `json:"distance_km"`
	BearingDeg      int             `json:"bearing_deg"`
	NightlyPriceUSD int             `json:"nightly_price_usd"`
	Available       bool            `json:"available"`
	AsOf            string          `json:"as_of"`
	PhotoURL        *string         `json:"photo_url"`
	PhotoPage       *string         `json:"photo_page"`
	PhotoCredit     *string         `json:"photo_credit"`
	History         json.RawMessage `json:"history"`
}

// Store is what the HTTP handlers need from the database.
type Store interface {
	Ping(ctx context.Context) error
	Events(ctx context.Context, seriesID string, season int) ([]Event, error)
	Event(ctx context.Context, id int64) (Event, error)
	Stays(ctx context.Context, eventID int64) ([]Stay, error)
	Pace(ctx context.Context, eventID int64) ([]PaceRow, error)
	Drivers(ctx context.Context, eventID int64) ([]DriverRow, error)
	Entries(ctx context.Context, eventID int64) ([]EntryRow, error)
}

type pgStore struct{ pool *pgxpool.Pool }

func (s pgStore) Ping(ctx context.Context) error { return s.pool.Ping(ctx) }

const eventSelect = `
SELECT e.id, e.series_id, s.name, e.season, e.round, e.venue_name, e.slug,
       e.start_date, e.end_date, e.source_url,
       c.id, c.name, c.locality, c.country, c.lat, c.lon
FROM events e
JOIN series s ON s.id = e.series_id
LEFT JOIN circuits c ON c.id = e.circuit_id`

func scanEvent(row pgx.Row) (Event, error) {
	var (
		e                            Event
		start, end                   time.Time
		cID, cName, cLocality, cCtry *string
		cLat, cLon                   *float64
	)
	err := row.Scan(&e.ID, &e.SeriesID, &e.SeriesName, &e.Season, &e.Round, &e.Venue, &e.Slug,
		&start, &end, &e.SourceURL, &cID, &cName, &cLocality, &cCtry, &cLat, &cLon)
	if err != nil {
		return Event{}, err
	}
	e.StartDate = start.Format(time.DateOnly)
	e.EndDate = end.Format(time.DateOnly)
	if cID != nil {
		e.Circuit = &Circuit{ID: *cID, Name: *cName, Locality: *cLocality, Country: *cCtry, Lat: *cLat, Lon: *cLon}
	}
	return e, nil
}

// Events lists events in date order. An empty seriesID or a zero season means "any".
func (s pgStore) Events(ctx context.Context, seriesID string, season int) ([]Event, error) {
	rows, err := s.pool.Query(ctx, eventSelect+`
WHERE ($1 = '' OR e.series_id = $1) AND ($2 = 0 OR e.season = $2)
ORDER BY e.start_date, e.id`, seriesID, season)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := []Event{}
	for rows.Next() {
		e, err := scanEvent(rows)
		if err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	return events, rows.Err()
}

func (s pgStore) Event(ctx context.Context, id int64) (Event, error) {
	e, err := scanEvent(s.pool.QueryRow(ctx, eventSelect+` WHERE e.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return Event{}, ErrNotFound
	}
	return e, err
}

// Stays returns each stay's most recent snapshot for the event, nearest first,
// with its full price history.
func (s pgStore) Stays(ctx context.Context, eventID int64) ([]Stay, error) {
	rows, err := s.pool.Query(ctx, `
WITH latest AS (
    SELECT max(snapshot_date) AS d FROM stay_price_snapshots WHERE event_id = $1
)
SELECT st.id, st.title, st.kind, st.sleeps, st.distance_km::float8, st.bearing_deg,
       sp.nightly_price_usd, sp.available, sp.snapshot_date,
       st.photo_url, st.photo_page, st.photo_credit,
       (SELECT json_agg(json_build_object('date', h.snapshot_date, 'price', h.nightly_price_usd)
                        ORDER BY h.snapshot_date)
        FROM stay_price_snapshots h
        WHERE h.stay_id = st.id AND h.event_id = $1)
FROM stays st
JOIN stay_price_snapshots sp ON sp.stay_id = st.id AND sp.event_id = $1
JOIN latest ON sp.snapshot_date = latest.d
ORDER BY st.distance_km, st.id`, eventID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	stays := []Stay{}
	for rows.Next() {
		var (
			st      Stay
			asOf    time.Time
			history []byte
		)
		if err := rows.Scan(&st.ID, &st.Title, &st.Kind, &st.Sleeps, &st.DistanceKm, &st.BearingDeg,
			&st.NightlyPriceUSD, &st.Available, &asOf,
			&st.PhotoURL, &st.PhotoPage, &st.PhotoCredit, &history); err != nil {
			return nil, err
		}
		st.AsOf = asOf.Format(time.DateOnly)
		st.History = history
		stays = append(stays, st)
	}
	return stays, rows.Err()
}
