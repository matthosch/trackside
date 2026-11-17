export interface Circuit {
  id: string;
  name: string;
  locality: string;
  country: string;
  lat: number;
  lon: number;
}

export interface RaceEvent {
  id: number;
  series_id: string;
  series_name: string;
  season: number;
  round: number | null;
  venue: string;
  slug: string;
  start_date: string;
  end_date: string;
  source_url: string;
  circuit: Circuit | null;
}

export interface Stay {
  id: string;
  title: string;
  kind: string;
  sleeps: number;
  distance_km: number;
  bearing_deg: number;
  nightly_price_usd: number;
  available: boolean;
  as_of: string;
  photo_url: string | null;
  photo_page: string | null;
  photo_credit: string | null;
  history: { date: string; price: number }[];
}

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error ?? `Request failed (${response.status})`);
  }
  return response.json();
}

export interface PaceRow {
  source: string;
  source_name: string;
  season: number;
  model: string;
  rank: number;
  cars: number;
  best_lap_ms: number;
  best_gap_ms: number;
  race_pace_ms: number | null;
  race_gap_ms: number | null;
}

export const listEvents = (signal: AbortSignal) => get<RaceEvent[]>("/api/events", signal);
export const getEvent = (id: string, signal: AbortSignal) => get<RaceEvent>(`/api/events/${id}`, signal);
export const listStays = (id: string, signal: AbortSignal) => get<Stay[]>(`/api/events/${id}/stays`, signal);
export const listPace = (id: string, signal: AbortSignal) => get<PaceRow[]>(`/api/events/${id}/pace`, signal);
