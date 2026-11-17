import { Link } from "react-router-dom";

import { listEvents } from "./api";
import { countdown, daysUntil, formatRange } from "./dates";
import { useFetch } from "./useFetch";

export function CalendarPage() {
  const events = useFetch("events", listEvents);

  if (events.status === "loading") return <p className="state">Loading the calendar…</p>;
  if (events.status === "error") return <p className="state error">Could not load the calendar: {events.message}</p>;
  if (events.data.length === 0) {
    return <p className="state">No races loaded yet. Run the seed job to fetch the calendar.</p>;
  }

  const next = events.data.find((e) => daysUntil(e.end_date) >= 0);

  return (
    <>
      <span className="label">The calendar</span>
      <h1>Pick a race</h1>
      <ol className="rounds">
        {events.data.map((event) => (
          <li key={event.id} className={event.id === next?.id ? "next" : undefined}>
            <Link to={`/events/${event.id}`}>
              <span className="round">{event.round ? `R${event.round}` : "—"}</span>
              <span className="what">
                <b>
                  {event.venue}
                  {event.id === next?.id && <i className="tag">Next up</i>}
                </b>
                <span>
                  {event.series_name}
                  {event.circuit ? ` · ${event.circuit.locality}` : ""}
                </span>
              </span>
              <span className="when">
                <span>{formatRange(event.start_date, event.end_date)}</span>
                <span className="count">{countdown(event.start_date, event.end_date)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </>
  );
}
