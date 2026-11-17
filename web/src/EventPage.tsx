import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getEvent, listStays, type Circuit, type Stay } from "./api";
import { countdown, formatRange } from "./dates";
import { PacePanel } from "./PacePanel";
import { StayMap } from "./StayMap";
import { useFetch } from "./useFetch";

type SortKey = "distance" | "price";

export function EventPage() {
  const { id = "" } = useParams();
  const event = useFetch(`event:${id}`, (signal) => getEvent(id, signal));
  const stays = useFetch(`stays:${id}`, (signal) => listStays(id, signal));

  if (event.status === "loading") return <p className="state">Loading the race…</p>;
  if (event.status === "error") {
    return (
      <p className="state error">
        {event.message}. <Link to="/">Back to the calendar</Link>
      </p>
    );
  }

  const e = event.data;
  return (
    <>
      <Link to="/" className="back">
        <span>← Calendar</span>
      </Link>
      <span className="label">
        {e.series_name} {e.season}
        {e.round ? ` · Round ${e.round}` : ""}
      </span>
      <h1>{e.venue}</h1>
      <p className="meta">
        {formatRange(e.start_date, e.end_date)} · {countdown(e.start_date, e.end_date)}
        {e.circuit ? ` · ${e.circuit.locality}` : ""} ·{" "}
        <a href={e.source_url} target="_blank" rel="noreferrer">
          Official event page
        </a>
      </p>

      <section>
        <h2>What to watch</h2>
        <PacePanel eventId={id} />
      </section>

      <section>
        <h2>Where to stay</h2>
        {stays.status === "loading" && <p className="state">Loading stays…</p>}
        {stays.status === "error" && <p className="state error">Could not load stays: {stays.message}</p>}
        {stays.status === "ok" &&
          (stays.data.length === 0 ? (
            <p className="state">
              {e.circuit ? "No price snapshots for this race yet." : "This venue is not matched to a circuit yet, so it has no stays."}
            </p>
          ) : (
            <StayList stays={stays.data} circuit={e.circuit} />
          ))}
      </section>
    </>
  );
}

function StayList({ stays, circuit }: { stays: Stay[]; circuit: Circuit | null }) {
  const [sort, setSort] = useState<SortKey>("distance");
  const [hideBooked, setHideBooked] = useState(false);
  const [active, setActive] = useState<string | null>(null);

  const shown = useMemo(() => {
    const list = hideBooked ? stays.filter((s) => s.available) : [...stays];
    return list.sort((a, b) =>
      sort === "distance" ? a.distance_km - b.distance_km : a.nightly_price_usd - b.nightly_price_usd,
    );
  }, [stays, sort, hideBooked]);

  const availableCount = stays.filter((s) => s.available).length;

  return (
    <div className="stay-layout">
      <div>
        <div className="controls">
          <span>
            {availableCount} of {stays.length} available · prices as of {stays[0].as_of}
          </span>
          <label>
            Sort by{" "}
            <select value={sort} onChange={(ev) => setSort(ev.target.value as SortKey)}>
              <option value="distance">Distance</option>
              <option value="price">Price</option>
            </select>
          </label>
          <label>
            <input type="checkbox" checked={hideBooked} onChange={(ev) => setHideBooked(ev.target.checked)} /> Hide
            booked
          </label>
        </div>
        <ul className="stays">
          {shown.map((stay) => (
            <li
              key={stay.id}
              className={`stay${stay.available ? "" : " booked"}${stay.id === active ? " active" : ""}`}
              onMouseEnter={() => setActive(stay.id)}
              onMouseLeave={() => setActive(null)}
            >
              {stay.photo_url && (
                <div className="photo">
                  <img
                    src={`${stay.photo_url}?w=320&h=320&fit=crop&q=70&auto=format`}
                    alt=""
                  />
                  {stay.photo_page && (
                    <a href={stay.photo_page} target="_blank" rel="noreferrer" title={`Photo by @${stay.photo_credit} on Unsplash`}>
                      @{stay.photo_credit} / Unsplash
                    </a>
                  )}
                </div>
              )}
              <span className="label">
                {stay.kind} · sleeps {stay.sleeps}
              </span>
              <b>{stay.title}</b>
              <div className="row">
                <span>{stay.distance_km.toFixed(1)} km to gate</span>
                <Sparkline history={stay.history} />
                <span className="price">{stay.available ? `$${stay.nightly_price_usd} / night` : "Booked"}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
      {circuit && <StayMap circuit={circuit} stays={shown} active={active} onHover={setActive} />}
    </div>
  );
}

function Sparkline({ history }: { history: Stay["history"] }) {
  if (history.length < 2) return <span />;
  const prices = history.map((h) => h.price);
  const min = Math.min(...prices);
  const span = Math.max(...prices) - min || 1;
  const points = prices
    .map((p, i) => `${((i / (prices.length - 1)) * 80).toFixed(1)},${(18 - ((p - min) / span) * 16).toFixed(1)}`)
    .join(" ");
  const change = prices[prices.length - 1] - prices[0];
  return (
    <svg className="spark" viewBox="0 0 80 20" role="img" aria-label={`Price ${change >= 0 ? "up" : "down"} $${Math.abs(change)} over ${history.length} days`}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
