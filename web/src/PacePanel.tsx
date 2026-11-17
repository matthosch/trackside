import { useMemo, useState } from "react";

import { listPace, type PaceRow } from "./api";
import { useFetch } from "./useFetch";

function lapTime(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  const seconds = ((ms % 60_000) / 1000).toFixed(3).padStart(6, "0");
  return `${minutes}:${seconds}`;
}

function gap(ms: number | null): string {
  if (ms === null) return "";
  return ms === 0 ? "—" : `+${(ms / 1000).toFixed(3)}`;
}

type Group = { key: string; sourceName: string; season: number; rows: PaceRow[] };

export function PacePanel({ eventId }: { eventId: string }) {
  const pace = useFetch(`pace:${eventId}`, (signal) => listPace(eventId, signal));
  const [selected, setSelected] = useState<string | null>(null);

  const groups = useMemo<Group[]>(() => {
    if (pace.status !== "ok") return [];
    const byKey = new Map<string, Group>();
    for (const row of pace.data) {
      const key = `${row.source}:${row.season}`;
      if (!byKey.has(key)) byKey.set(key, { key, sourceName: row.source_name, season: row.season, rows: [] });
      byKey.get(key)!.rows.push(row);
    }
    // Most recent season first; within a season, the series with the most cars.
    return [...byKey.values()].sort((a, b) => b.season - a.season || b.rows.length - a.rows.length);
  }, [pace]);

  if (pace.status === "loading") return <p className="state">Loading pace…</p>;
  if (pace.status === "error") return <p className="state error">Could not load pace: {pace.message}</p>;
  if (groups.length === 0) {
    return <p className="state">No timing data for this circuit in the seasons loaded so far.</p>;
  }

  const group = groups.find((g) => g.key === selected) ?? groups[0];
  const hasRacePace = group.rows.some((r) => r.race_pace_ms !== null);
  const maxGap = Math.max(1, ...group.rows.map((r) => (hasRacePace ? r.race_gap_ms : r.best_gap_ms) ?? 0));

  return (
    <div className="pace">
      <div className="pace-tabs" role="tablist" aria-label="Series and season">
        {groups.map((g) => (
          <button
            key={g.key}
            role="tab"
            aria-selected={g.key === group.key}
            className={g.key === group.key ? "on" : undefined}
            onClick={() => setSelected(g.key)}
          >
            <span>
              {g.season} · {g.sourceName}
            </span>
          </button>
        ))}
      </div>

      <div className="tower">
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>P</th>
                <th>Car model</th>
                <th>Cars</th>
                <th>Best lap</th>
                {hasRacePace && <th>Race pace</th>}
                <th>Gap</th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row) => {
                const rowGap = hasRacePace ? row.race_gap_ms : row.best_gap_ms;
                return (
                  <tr key={row.model}>
                    <td>
                      <span className="pos">{row.rank}</span>
                    </td>
                    <td className="car">{row.model}</td>
                    <td>{row.cars}</td>
                    <td>{lapTime(row.best_lap_ms)}</td>
                    {hasRacePace && <td>{row.race_pace_ms === null ? "—" : lapTime(row.race_pace_ms)}</td>}
                    <td className="gap">
                      <span>{gap(rowGap)}</span>
                      {rowGap !== null && rowGap > 0 && (
                        <i style={{ width: `${Math.max(4, (rowGap / maxGap) * 100)}%` }} aria-hidden="true" />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <p className="pace-note">
        {hasRacePace
          ? "Ranked by race pace: the mean of the 10 fastest green-flag race laps by each model's best car. "
          : "Ranked by best lap: no race had enough clean laps for race pace. "}
        Pit laps, out-laps, caution laps, and timing glitches are excluded. Derived from timing data by Al Kamel
        Systems.
      </p>
    </div>
  );
}
