// Win-probability timeline for the Matchup chart.
//
// A fantasy week's games come in windows (Thursday night, Sunday, Monday)
// separated by days of nothing. Plotting real time would squeeze Sunday into a
// sliver, so the x-axis is "game time": each window keeps its true length and
// the dead time between windows is cut out. A point recorded between windows
// (say, an injury update on Saturday) lands at the start of the next one.

export interface OddsChange {
  id: string;
  name: string;
  position: string | null;
  side: "user" | "opp";
  delta: number;
  points: number;
}
export interface OddsSwing {
  delta: number;
  drivers: OddsChange[];
}
export interface OddsPoint {
  t: string | null;
  win_probability: number;
  user_points: number | null;
  opp_points: number | null;
  delta?: number | null;
  changes?: OddsChange[];
  swing?: OddsSwing | null;
}
export interface Kickoff {
  t: string;
  home: string;
  away: string;
}
export interface OddsHistory {
  week: number | null;
  points: OddsPoint[];
  kickoffs?: Kickoff[];
  window_start?: string | null;
  swing_threshold?: number;
}

const MIN = 60_000;
// Kickoff to final whistle, with room for overtime.
const GAME_MS = 225 * MIN;
// Kickoffs closer than this to the previous window's end join that window, so
// a Sunday (1:00, 4:25, then the night game) is one stretch.
const MERGE_GAP_MS = 90 * MIN;
// Kickoffs this close together share one marker ("1:00", "4:05/4:25").
const SLOT_GAP_MS = 30 * MIN;

/** Parse the API's naive-UTC ISO timestamps. */
export function parseUtc(t: string | null | undefined): number | null {
  if (!t) return null;
  const norm = /[Z]|[+-]\d\d:?\d\d$/.test(t) ? t : `${t}Z`;
  const ms = new Date(norm).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export interface GameWindow {
  start: number; // first kickoff (ms)
  end: number; // last game's final, or now if it's still on
  offset: number; // x of `start` on the compressed axis
  slots: number[]; // kickoff times worth a marker
}

/** Group kickoffs into game windows that have started by `now`. */
export function buildWindows(kickoffs: number[], now: number): GameWindow[] {
  const ks = [...new Set(kickoffs)].sort((a, b) => a - b).filter((k) => k <= now);
  const windows: GameWindow[] = [];
  for (const k of ks) {
    const cur = windows[windows.length - 1];
    if (cur && k <= cur.end + MERGE_GAP_MS) {
      cur.end = Math.max(cur.end, k + GAME_MS);
      if (k - cur.slots[cur.slots.length - 1] >= SLOT_GAP_MS) cur.slots.push(k);
    } else {
      windows.push({ start: k, end: k + GAME_MS, offset: 0, slots: [k] });
    }
  }
  let offset = 0;
  for (const w of windows) {
    w.end = Math.min(w.end, now);
    w.offset = offset;
    offset += Math.max(w.end - w.start, MIN);
  }
  return windows;
}

/** Position of a timestamp on the compressed axis. */
export function toX(t: number, windows: GameWindow[]): number {
  if (!windows.length) return 0;
  for (const w of windows) {
    if (t < w.start) return w.offset; // between windows → next window's start
    if (t <= w.end) return w.offset + (t - w.start);
  }
  const last = windows[windows.length - 1];
  return last.offset + Math.max(last.end - last.start, MIN);
}

export function axisEnd(windows: GameWindow[]): number {
  if (!windows.length) return 0;
  const last = windows[windows.length - 1];
  return last.offset + Math.max(last.end - last.start, MIN);
}

export interface ChartDatum {
  x: number;
  t: number;
  you: number;
  point: OddsPoint | null; // null for the "now" extension
}

export type TimelineView = "week" | "today";

export interface Timeline {
  windows: GameWindow[];
  data: ChartDatum[];
  end: number;
  swings: { datum: ChartDatum; swing: OddsSwing }[];
}

function sameLocalDay(a: number, b: number): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return (
    da.getFullYear() === db.getFullYear() &&
    da.getMonth() === db.getMonth() &&
    da.getDate() === db.getDate()
  );
}

/** Does `now`'s local day have a game window that's started? */
export function hasGamesToday(history: OddsHistory, now: number): boolean {
  return (history.kickoffs ?? []).some((k) => {
    const t = parseUtc(k.t);
    return t != null && t <= now && sameLocalDay(t, now);
  });
}

export function buildTimeline(
  history: OddsHistory,
  now: number,
  view: TimelineView,
): Timeline {
  const pts = history.points
    .map((p) => ({ p, t: parseUtc(p.t) }))
    .filter((x): x is { p: OddsPoint; t: number } => x.t != null)
    .sort((a, b) => a.t - b.t);

  let kicks = (history.kickoffs ?? [])
    .map((k) => parseUtc(k.t))
    .filter((t): t is number => t != null);
  if (view === "today") kicks = kicks.filter((t) => sameLocalDay(t, now));

  let windows = buildWindows(kicks, now);
  if (!windows.length && pts.length) {
    // No schedule to go on: plain time from the first snapshot to now.
    const start = view === "today" ? Math.max(pts[0].t, startOfDay(now)) : pts[0].t;
    windows = [{ start, end: Math.max(now, start + MIN), offset: 0, slots: [] }];
  }

  const first = windows[0]?.start ?? -Infinity;
  // Today's view starts at today's first kickoff, carrying in the odds as they
  // stood then (the last earlier snapshot), so the line doesn't start mid-air.
  const before = pts.filter((x) => x.t < first);
  const inView = pts.filter((x) => x.t >= first);
  const seed = view === "today" && before.length ? [before[before.length - 1]] : [];

  const data: ChartDatum[] = [
    ...seed.map(({ p }) => ({
      x: 0,
      t: first,
      you: pct(p.win_probability),
      point: { ...p, swing: null },
    })),
    ...(view === "week" ? before : []).map(({ p, t }) => ({
      x: 0,
      t,
      you: pct(p.win_probability),
      point: p,
    })),
    ...inView.map(({ p, t }) => ({
      x: toX(t, windows),
      t,
      you: pct(p.win_probability),
      point: p,
    })),
  ];
  const end = axisEnd(windows);
  const last = data[data.length - 1];
  if (last && last.x < end) {
    // Carry the latest odds out to now.
    data.push({ x: end, t: Math.max(now, last.t), you: last.you, point: null });
  }
  const swings = data
    .filter((d) => d.point?.swing)
    .map((d) => ({ datum: d, swing: d.point!.swing! }));
  return { windows, data, end, swings };
}

function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function pct(p: number): number {
  return Math.round(p * 1000) / 10;
}

/** "Gibbs" from "Jahmyr Gibbs"; team defenses keep their full name. */
export function shortName(c: Pick<OddsChange, "name" | "position">): string {
  const pos = (c.position ?? "").toUpperCase();
  if (pos === "DEF" || pos === "DST" || pos === "D/ST") return c.name;
  const parts = c.name.trim().split(/\s+/);
  return parts.length > 1 ? parts.slice(1).join(" ") : c.name;
}

export function signed(n: number, digits = 1): string {
  const s = Math.abs(n).toFixed(digits);
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s;
}

/** Percentage-point label for a probability move: +8% / −5%. */
export function swingPct(delta: number): string {
  return `${signed(Math.round(delta * 100), 0)}%`;
}

/** Chart label for a swing: "Gibbs +8%". */
export function swingLabel(s: OddsSwing): string {
  // No starter's points moved: injury news or a lineup change did it.
  const who = s.drivers[0] ? shortName(s.drivers[0]) : "Update";
  return `${who} ${swingPct(s.delta)}`;
}

export function fmtClock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function fmtDayClock(ms: number): string {
  return new Date(ms).toLocaleString([], {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}
