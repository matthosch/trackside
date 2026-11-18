package main

import (
	"context"
	"errors"
	"net/http"
)

// DriverRow is one driver's pace at a circuit in one season, ranked within their class.
type DriverRow struct {
	Source     string `json:"source"`
	SourceName string `json:"source_name"`
	Season     int    `json:"season"`
	Class      string `json:"class"`
	Driver     string `json:"driver"`
	Team       string `json:"team"`
	CarNumber  string `json:"car_number"`
	Model      string `json:"model"`
	Rank       int    `json:"rank"`
	ValidLaps  int    `json:"valid_laps"`
	BestLapMs  int    `json:"best_lap_ms"`
	BestGapMs  int    `json:"best_gap_ms"`
	RacePaceMs *int   `json:"race_pace_ms"`
	RaceGapMs  *int   `json:"race_gap_ms"`
}

// EntryRow is one car (team entry) at a circuit in one season, ranked within its class.
type EntryRow struct {
	Source     string   `json:"source"`
	SourceName string   `json:"source_name"`
	Season     int      `json:"season"`
	Class      string   `json:"class"`
	CarNumber  string   `json:"car_number"`
	Team       string   `json:"team"`
	Model      string   `json:"model"`
	Drivers    []string `json:"drivers"`
	Rank       int      `json:"rank"`
	BestLapMs  int      `json:"best_lap_ms"`
	BestGapMs  int      `json:"best_gap_ms"`
	RacePaceMs *int     `json:"race_pace_ms"`
	RaceGapMs  *int     `json:"race_gap_ms"`
}

func sourceName(source string) string {
	if name := sourceNames[source]; name != "" {
		return name
	}
	return source
}

func (s pgStore) Drivers(ctx context.Context, eventID int64) ([]DriverRow, error) {
	rows, err := s.pool.Query(ctx, `
SELECT d.source, d.season, d.class, d.driver_name, coalesce(d.team, ''), d.car_number,
       coalesce(d.model, ''), d.rank::int, d.valid_laps::int, d.best_lap_ms, d.best_gap_ms,
       d.race_pace_ms, d.race_gap_ms
FROM events e
JOIN marts.driver_pace d ON d.circuit_id = e.circuit_id
WHERE e.id = $1
ORDER BY d.season DESC, d.source, d.class, d.rank, d.driver_name`, eventID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []DriverRow{}
	for rows.Next() {
		var r DriverRow
		if err := rows.Scan(&r.Source, &r.Season, &r.Class, &r.Driver, &r.Team, &r.CarNumber, &r.Model,
			&r.Rank, &r.ValidLaps, &r.BestLapMs, &r.BestGapMs, &r.RacePaceMs, &r.RaceGapMs); err != nil {
			return nil, err
		}
		r.SourceName = sourceName(r.Source)
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s pgStore) Entries(ctx context.Context, eventID int64) ([]EntryRow, error) {
	rows, err := s.pool.Query(ctx, `
SELECT p.source, p.season, p.class, p.car_number, coalesce(p.team, ''), coalesce(p.model, ''),
       p.drivers, p.rank::int, p.best_lap_ms, p.best_gap_ms, p.race_pace_ms, p.race_gap_ms
FROM events e
JOIN marts.entry_pace p ON p.circuit_id = e.circuit_id
WHERE e.id = $1
ORDER BY p.season DESC, p.source, p.class, p.rank, p.car_number`, eventID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := []EntryRow{}
	for rows.Next() {
		var r EntryRow
		if err := rows.Scan(&r.Source, &r.Season, &r.Class, &r.CarNumber, &r.Team, &r.Model, &r.Drivers,
			&r.Rank, &r.BestLapMs, &r.BestGapMs, &r.RacePaceMs, &r.RaceGapMs); err != nil {
			return nil, err
		}
		r.SourceName = sourceName(r.Source)
		out = append(out, r)
	}
	return out, rows.Err()
}

// forEvent answers 404 for an unknown event, then writes whatever load returns.
func forEvent[T any](s *server, what string, load func(context.Context, int64) ([]T, error)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id, ok := s.eventID(w, r)
		if !ok {
			return
		}
		if _, err := s.store.Event(r.Context(), id); errors.Is(err, ErrNotFound) {
			s.writeError(w, r, http.StatusNotFound, "event not found", err)
			return
		} else if err != nil {
			s.writeError(w, r, http.StatusInternalServerError, "could not load event", err)
			return
		}
		rows, err := load(r.Context(), id)
		if err != nil {
			s.writeError(w, r, http.StatusInternalServerError, "could not load "+what, err)
			return
		}
		s.writeJSON(w, http.StatusOK, rows)
	}
}
