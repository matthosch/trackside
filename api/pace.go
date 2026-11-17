package main

import (
	"context"
	"errors"
	"net/http"
)

// PaceRow is one car model's pace at a circuit in one season, from one timing source.
// Only derived aggregates are exposed; raw timing data never leaves the pipeline.
type PaceRow struct {
	Source     string `json:"source"`
	SourceName string `json:"source_name"`
	Season     int    `json:"season"`
	Model      string `json:"model"`
	Rank       int    `json:"rank"`
	Cars       int    `json:"cars"`
	BestLapMs  int    `json:"best_lap_ms"`
	BestGapMs  int    `json:"best_gap_ms"`
	RacePaceMs *int   `json:"race_pace_ms"`
	RaceGapMs  *int   `json:"race_gap_ms"`
}

var sourceNames = map[string]string{
	"imsa":        "IMSA WeatherTech GTD",
	"sro_america": "GT World Challenge America",
}

func (s pgStore) Pace(ctx context.Context, eventID int64) ([]PaceRow, error) {
	rows, err := s.pool.Query(ctx, `
SELECT p.source, p.season, p.model, p.rank::int, p.cars::int, p.best_lap_ms, p.best_gap_ms,
       p.race_pace_ms, p.race_gap_ms::int
FROM events e
JOIN marts.circuit_pace p ON p.circuit_id = e.circuit_id
WHERE e.id = $1
ORDER BY p.season DESC, p.source, p.rank, p.model`, eventID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	pace := []PaceRow{}
	for rows.Next() {
		var r PaceRow
		if err := rows.Scan(&r.Source, &r.Season, &r.Model, &r.Rank, &r.Cars, &r.BestLapMs, &r.BestGapMs,
			&r.RacePaceMs, &r.RaceGapMs); err != nil {
			return nil, err
		}
		r.SourceName = sourceNames[r.Source]
		if r.SourceName == "" {
			r.SourceName = r.Source
		}
		pace = append(pace, r)
	}
	return pace, rows.Err()
}

func (s *server) listPace(w http.ResponseWriter, r *http.Request) {
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
	pace, err := s.store.Pace(r.Context(), id)
	if err != nil {
		s.writeError(w, r, http.StatusInternalServerError, "could not load pace", err)
		return
	}
	s.writeJSON(w, http.StatusOK, pace)
}
