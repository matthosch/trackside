package main

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/prometheus/client_golang/prometheus/promhttp"
)

type server struct {
	store Store
	log   *slog.Logger
}

func (s *server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.Handle("GET /metrics", promhttp.Handler())
	mux.HandleFunc("GET /api/events", s.listEvents)
	mux.HandleFunc("GET /api/events/{id}", s.getEvent)
	mux.HandleFunc("GET /api/events/{id}/stays", s.listStays)
	mux.HandleFunc("GET /api/events/{id}/pace", s.listPace)
	mux.HandleFunc("GET /api/events/{id}/drivers", forEvent(s, "drivers", s.store.Drivers))
	mux.HandleFunc("GET /api/events/{id}/teams", forEvent(s, "teams", s.store.Entries))
	return instrument(s.log, mux)
}

func (s *server) writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		s.log.Error("write response", "error", err)
	}
}

func (s *server) writeError(w http.ResponseWriter, r *http.Request, status int, msg string, err error) {
	if status >= 500 {
		s.log.Error(msg, "error", err, "path", r.URL.Path)
	}
	s.writeJSON(w, status, map[string]string{"error": msg})
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	if err := s.store.Ping(r.Context()); err != nil {
		s.writeError(w, r, http.StatusServiceUnavailable, "database unavailable", err)
		return
	}
	s.writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (s *server) listEvents(w http.ResponseWriter, r *http.Request) {
	season := 0
	if raw := r.URL.Query().Get("season"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n <= 0 {
			s.writeError(w, r, http.StatusBadRequest, "season must be a year", err)
			return
		}
		season = n
	}
	events, err := s.store.Events(r.Context(), r.URL.Query().Get("series"), season)
	if err != nil {
		s.writeError(w, r, http.StatusInternalServerError, "could not load events", err)
		return
	}
	s.writeJSON(w, http.StatusOK, events)
}

func (s *server) eventID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		s.writeError(w, r, http.StatusBadRequest, "event id must be a number", err)
		return 0, false
	}
	return id, true
}

func (s *server) getEvent(w http.ResponseWriter, r *http.Request) {
	id, ok := s.eventID(w, r)
	if !ok {
		return
	}
	event, err := s.store.Event(r.Context(), id)
	if errors.Is(err, ErrNotFound) {
		s.writeError(w, r, http.StatusNotFound, "event not found", err)
		return
	}
	if err != nil {
		s.writeError(w, r, http.StatusInternalServerError, "could not load event", err)
		return
	}
	s.writeJSON(w, http.StatusOK, event)
}

func (s *server) listStays(w http.ResponseWriter, r *http.Request) {
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
	stays, err := s.store.Stays(r.Context(), id)
	if err != nil {
		s.writeError(w, r, http.StatusInternalServerError, "could not load stays", err)
		return
	}
	s.writeJSON(w, http.StatusOK, stays)
}
