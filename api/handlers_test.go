package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus/testutil"
)

type fakeStore struct {
	events  []Event
	stays   []Stay
	pingErr error
	failAll bool

	gotSeries string
	gotSeason int
}

func (f *fakeStore) Ping(context.Context) error { return f.pingErr }

func (f *fakeStore) Events(_ context.Context, series string, season int) ([]Event, error) {
	f.gotSeries, f.gotSeason = series, season
	if f.failAll {
		return nil, errors.New("boom")
	}
	return f.events, nil
}

func (f *fakeStore) Event(_ context.Context, id int64) (Event, error) {
	for _, e := range f.events {
		if e.ID == id {
			return e, nil
		}
	}
	return Event{}, ErrNotFound
}

func (f *fakeStore) Stays(context.Context, int64) ([]Stay, error) { return f.stays, nil }

func get(t *testing.T, store Store, path string) *httptest.ResponseRecorder {
	t.Helper()
	srv := &server{store: store, log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	rec := httptest.NewRecorder()
	srv.routes().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

func TestListEventsPassesFilters(t *testing.T) {
	store := &fakeStore{events: []Event{{ID: 1, Venue: "Sonoma Raceway"}}}
	rec := get(t, store, "/api/events?series=gtwc-america&season=2027")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if store.gotSeries != "gtwc-america" || store.gotSeason != 2027 {
		t.Errorf("filters = %q, %d", store.gotSeries, store.gotSeason)
	}
	var got []Event
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil || len(got) != 1 {
		t.Fatalf("body = %s (err %v)", rec.Body, err)
	}
}

func TestStatusCodes(t *testing.T) {
	store := &fakeStore{events: []Event{{ID: 1}}, stays: []Stay{}}
	cases := []struct {
		path string
		want int
	}{
		{"/api/events?season=soon", http.StatusBadRequest},
		{"/api/events/1", http.StatusOK},
		{"/api/events/99", http.StatusNotFound},
		{"/api/events/abc", http.StatusBadRequest},
		{"/api/events/1/stays", http.StatusOK},
		{"/api/events/99/stays", http.StatusNotFound},
		{"/healthz", http.StatusOK},
		{"/nope", http.StatusNotFound},
	}
	for _, c := range cases {
		if got := get(t, store, c.path).Code; got != c.want {
			t.Errorf("GET %s = %d, want %d", c.path, got, c.want)
		}
	}
}

func TestStoreFailureIsA500WithoutLeakingTheCause(t *testing.T) {
	rec := get(t, &fakeStore{failAll: true}, "/api/events")
	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want 500", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "boom") {
		t.Errorf("internal error leaked to client: %s", rec.Body)
	}
}

func TestHealthReportsDatabaseOutage(t *testing.T) {
	rec := get(t, &fakeStore{pingErr: errors.New("down")}, "/healthz")
	if rec.Code != http.StatusServiceUnavailable {
		t.Errorf("status = %d, want 503", rec.Code)
	}
}

func TestMetricsUseRoutePatternNotRawPath(t *testing.T) {
	store := &fakeStore{events: []Event{{ID: 7}}}
	labels := []string{"GET /api/events/{id}", http.MethodGet, "200"}
	before := testutil.ToFloat64(httpRequests.WithLabelValues(labels...))
	get(t, store, "/api/events/7")
	if got := testutil.ToFloat64(httpRequests.WithLabelValues(labels...)) - before; got != 1 {
		t.Errorf("counter for route pattern rose by %v, want 1", got)
	}
}
