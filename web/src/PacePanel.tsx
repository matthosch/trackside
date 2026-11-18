import { useMemo, useState, type ReactNode } from "react";

import { listDrivers, listPace, listTeams, type DriverRow, type EntryRow, type PaceRow } from "./api";
import { useFetch } from "./useFetch";

type View = "drivers" | "teams" | "models";

const VIEWS: { id: View; label: string }[] = [
  { id: "drivers", label: "Drivers" },
  { id: "teams", label: "Teams" },
  { id: "models", label: "Car models" },
];

// Most prominent class first in each series.
const CLASS_ORDER = ["GTDPRO", "GTD", "PRO", "PRO-AM", "AM"];
const CLASS_LABELS: Record<string, string> = {
  GTDPRO: "GTD Pro",
  GTD: "GTD",
  PRO: "Pro",
  "PRO-AM": "Pro-Am",
  AM: "Am",
};

const TOP = 10;

function lapTime(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  const seconds = ((ms % 60_000) / 1000).toFixed(3).padStart(6, "0");
  return `${minutes}:${seconds}`;
}

function gapText(ms: number | null): string {
  if (ms === null) return "";
  return ms === 0 ? "—" : `+${(ms / 1000).toFixed(3)}`;
}

function classRank(c: string): number {
  const i = CLASS_ORDER.indexOf(c);
  return i === -1 ? CLASS_ORDER.length : i;
}

/** Fields every ranking row shares, whichever view it comes from. */
interface Ranked {
  key: string;
  rank: number;
  best_lap_ms: number;
  best_gap_ms: number;
  race_pace_ms: number | null;
  race_gap_ms: number | null;
}

type Group = { key: string; sourceName: string; season: number; size: number };

export function PacePanel({ eventId }: { eventId: string }) {
  const drivers = useFetch(`drivers:${eventId}`, (signal) => listDrivers(eventId, signal));
  const teams = useFetch(`teams:${eventId}`, (signal) => listTeams(eventId, signal));
  const models = useFetch(`pace:${eventId}`, (signal) => listPace(eventId, signal));

  const [view, setView] = useState<View>("drivers");
  const [groupKey, setGroupKey] = useState<string | null>(null);
  const [classPick, setClassPick] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  // Series and seasons come from the model ranking, which exists wherever laps do.
  const groups = useMemo<Group[]>(() => {
    if (models.status !== "ok") return [];
    const byKey = new Map<string, Group>();
    for (const row of models.data) {
      const key = `${row.source}:${row.season}`;
      const g = byKey.get(key) ?? { key, sourceName: row.source_name, season: row.season, size: 0 };
      g.size += row.cars;
      byKey.set(key, g);
    }
    return [...byKey.values()].sort((a, b) => b.season - a.season || b.size - a.size);
  }, [models]);

  const state = { drivers, teams, models }[view];
  if (models.status === "loading" || state.status === "loading") return <p className="state">Loading pace…</p>;
  if (models.status === "error") return <p className="state error">Could not load pace: {models.message}</p>;
  if (state.status === "error") return <p className="state error">Could not load {view}: {state.message}</p>;
  if (groups.length === 0) {
    return <p className="state">No timing data for this circuit in the seasons loaded so far.</p>;
  }

  const group = groups.find((g) => g.key === groupKey) ?? groups[0];
  const inGroup = <T extends { source: string; season: number }>(rows: T[]) =>
    rows.filter((r) => `${r.source}:${r.season}` === group.key);

  // Drivers and teams are ranked within a class; car models across the field.
  let classes: string[] = [];
  let klass: string | null = null;
  let rows: Ranked[] = [];
  let render: (row: Ranked) => ReactNode;
  let head: ReactNode;

  if (view === "models") {
    const data = inGroup((models.data as PaceRow[]) ?? []);
    rows = data.map((r) => ({ ...r, key: r.model }));
    const byKey = new Map(data.map((r) => [r.model, r]));
    head = (
      <>
        <th>Car model</th>
        <th>Cars</th>
      </>
    );
    render = (row) => {
      const r = byKey.get(row.key)!;
      return (
        <>
          <td className="car">{r.model}</td>
          <td>{r.cars}</td>
        </>
      );
    };
  } else {
    const data = inGroup(state.status === "ok" ? (state.data as (DriverRow | EntryRow)[]) : []);
    classes = [...new Set(data.map((r) => r.class))].sort((a, b) => classRank(a) - classRank(b));
    klass = classPick && classes.includes(classPick) ? classPick : classes[0] ?? null;
    const inClass = data.filter((r) => r.class === klass);

    if (view === "drivers") {
      const typed = inClass as DriverRow[];
      rows = typed.map((r) => ({ ...r, key: r.driver }));
      const byKey = new Map(typed.map((r) => [r.driver, r]));
      head = (
        <>
          <th>Driver</th>
          <th className="model">Car</th>
        </>
      );
      render = (row) => {
        const r = byKey.get(row.key)!;
        return (
          <>
            <td className="who">
              <b>{r.driver}</b>
              <span className="sub">
                <i className="num">#{r.car_number}</i> {r.team}
              </span>
            </td>
            <td className="model">{r.model}</td>
          </>
        );
      };
    } else {
      const typed = inClass as EntryRow[];
      rows = typed.map((r) => ({ ...r, key: r.car_number }));
      const byKey = new Map(typed.map((r) => [r.car_number, r]));
      head = (
        <>
          <th>Team</th>
          <th className="model">Car</th>
        </>
      );
      render = (row) => {
        const r = byKey.get(row.key)!;
        return (
          <>
            <td className="who">
              <b>
                <i className="num">#{r.car_number}</i> {r.team}
              </b>
              <span className="sub">{r.drivers.join(" · ")}</span>
            </td>
            <td className="model">{r.model}</td>
          </>
        );
      };
    }
  }

  const hasRacePace = rows.some((r) => r.race_pace_ms !== null);
  const gapOf = (r: Ranked) => (hasRacePace ? r.race_gap_ms : r.best_gap_ms);
  const maxGap = Math.max(1, ...rows.map((r) => gapOf(r) ?? 0));
  const visible = showAll ? rows : rows.slice(0, TOP);

  const pick = (fn: () => void) => () => {
    fn();
    setShowAll(false);
  };

  return (
    <div className="pace">
      <div className="pace-views" role="tablist" aria-label="Ranking">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            role="tab"
            aria-selected={v.id === view}
            className={v.id === view ? "on" : undefined}
            onClick={pick(() => setView(v.id))}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div className="pace-tabs" role="tablist" aria-label="Series and season">
        {groups.map((g) => (
          <button
            key={g.key}
            role="tab"
            aria-selected={g.key === group.key}
            className={g.key === group.key ? "on" : undefined}
            onClick={pick(() => setGroupKey(g.key))}
          >
            <span>
              {g.season} · {g.sourceName}
            </span>
          </button>
        ))}
      </div>

      {classes.length > 1 && (
        <div className="pace-classes" role="tablist" aria-label="Class">
          {classes.map((c) => (
            <button
              key={c}
              role="tab"
              aria-selected={c === klass}
              className={c === klass ? "on" : undefined}
              onClick={pick(() => setClassPick(c))}
            >
              {CLASS_LABELS[c] ?? c}
            </button>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <p className="state">Nothing to rank here.</p>
      ) : (
        <div className="tower">
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>P</th>
                  {head}
                  <th>Best lap</th>
                  {hasRacePace && <th>Race pace</th>}
                  <th>Gap</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => {
                  const g = gapOf(row);
                  return (
                    <tr key={row.key}>
                      <td>
                        <span className="pos">{row.rank}</span>
                      </td>
                      {render(row)}
                      <td>{lapTime(row.best_lap_ms)}</td>
                      {hasRacePace && <td>{row.race_pace_ms === null ? "—" : lapTime(row.race_pace_ms)}</td>}
                      <td className="gap">
                        <span>{gapText(g)}</span>
                        {g !== null && g > 0 && (
                          <i style={{ width: `${Math.max(4, (g / maxGap) * 100)}%` }} aria-hidden="true" />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length > TOP && (
            <button className="pace-more" onClick={() => setShowAll(!showAll)}>
              {showAll ? `Show top ${TOP}` : `Show all ${rows.length}`}
            </button>
          )}
        </div>
      )}

      <p className="pace-note">
        {view === "drivers" && "Each driver is judged on their own laps. "}
        {view === "teams" && "Each car combines all of its drivers' laps. "}
        {view === "models" && "Each model is judged by its best car. "}
        {hasRacePace
          ? "Ranked by race pace: the mean of the 10 fastest green-flag race laps. "
          : "Ranked by best lap: no race had enough clean laps for race pace. "}
        Pit laps, out-laps, caution laps, and timing glitches are excluded. Derived from timing data by Al Kamel
        Systems.
      </p>
    </div>
  );
}
