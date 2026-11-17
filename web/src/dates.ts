const DAY_MS = 86_400_000;

/** Parse a YYYY-MM-DD string as a local calendar date, not UTC midnight. */
export function parseDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatRange(startIso: string, endIso: string): string {
  const start = parseDate(startIso);
  const end = parseDate(endIso);
  const month = (d: Date) => d.toLocaleDateString("en-US", { month: "short" });
  if (startIso === endIso) return `${start.getDate()} ${month(start)} ${start.getFullYear()}`;
  if (start.getMonth() === end.getMonth()) {
    return `${start.getDate()}–${end.getDate()} ${month(end)} ${end.getFullYear()}`;
  }
  return `${start.getDate()} ${month(start)} – ${end.getDate()} ${month(end)} ${end.getFullYear()}`;
}

/** Whole days from today until the date; negative once it has passed. */
export function daysUntil(iso: string, now = new Date()): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((parseDate(iso).getTime() - today.getTime()) / DAY_MS);
}

export function countdown(startIso: string, endIso: string): string {
  const toStart = daysUntil(startIso);
  if (toStart > 1) return `In ${toStart} days`;
  if (toStart === 1) return "Tomorrow";
  if (daysUntil(endIso) >= 0) return "This weekend";
  return "Finished";
}
