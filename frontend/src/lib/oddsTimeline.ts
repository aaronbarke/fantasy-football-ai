// Win-probability timeline for the Matchup chart.
//
// The backend rebuilds the curve from play-by-play: a point every few minutes
// through each game window plus one just before and at every play that moved
// your starters' points. A fantasy week's games come in windows (Thursday
// night, Sunday, Monday) separated by days of nothing, so the x-axis is
// "game time": each window keeps its real length and the dead time between
// windows is cut out, the way ESPN's chart does it.

export interface OddsEvent {
  id: string;
  name: string;
  position: string | null;
  side: "user" | "opp";
  pts: number;
  label: string; // "45-yd TD run", "INT", "→ Injured Reserve, −16.6 proj"
  kind: "td" | "play" | "turnover" | "kick" | "news" | "points";
}
export interface OddsSwing {
  delta: number;
  drivers: OddsEvent[];
}
export interface OddsPoint {
  t: string | null;
  win_probability: number;
  user_points: number | null;
  opp_points: number | null;
  delta?: number | null;
  events?: OddsEvent[];
  swing?: OddsSwing | null;
}
export interface Kickoff {
  t: string;
  home: string;
  away: string;
  end?: string;
}
export interface OddsHistory {
  week: number | null;
  points: OddsPoint[];
  kickoffs?: Kickoff[];
  windows?: { start: string; end: string }[];
  window_start?: string | null;
  swing_threshold?: number;
  source?: "plays" | "estimate";
}

const MIN = 60_000;
const HOUR = 60 * MIN;
// Kickoffs this close together share one marker (1:00 and 1:05).
const SLOT_GAP_MS = 30 * MIN;

/** Parse the API's naive-UTC ISO timestamps. */
export function parseUtc(t: string | null | undefined): number | null {
  if (!t) return null;
  const norm = /[Z]|[+-]\d\d:?\d\d$/.test(t) ? t : `${t}Z`;
  const ms = new Date(norm).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export interface GameWindow {
  start: number;
  end: number;
  offset: number; // x of `start` on the compressed axis
  kickoffs: number[]; // distinct kickoff slots inside the window
}

function finishWindows(raw: { start: number; end: number }[], kicks: number[]): GameWindow[] {
  let offset = 0;
  return raw.map((w) => {
    const slots: number[] = [];
    for (const k of kicks) {
      if (k < w.start || k > w.end) continue;
      if (!slots.length || k - slots[slots.length - 1] >= SLOT_GAP_MS) slots.push(k);
    }
    const out = { start: w.start, end: w.end, offset, kickoffs: slots };
    offset += Math.max(w.end - w.start, MIN);
    return out;
  });
}

/** Position of a timestamp on the compressed axis. Anything between windows
 * (say, injury news on Saturday) lands at the start of the next window. */
export function toX(t: number, windows: GameWindow[]): number {
  for (const w of windows) {
    if (t < w.start) return w.offset;
    if (t <= w.end) return w.offset + (t - w.start);
  }
  return axisEnd(windows);
}

export function axisEnd(windows: GameWindow[]): number {
  if (!windows.length) return 0;
  const last = windows[windows.length - 1];
  return last.offset + Math.max(last.end - last.start, MIN);
}

export interface ChartDatum {
  x: number;
  t: number;
  you: number; // win probability, %
  point: OddsPoint;
  now?: boolean;
}

export type TimelineView = "week" | "today";

export interface Timeline {
  windows: GameWindow[];
  data: ChartDatum[];
  end: number;
  swings: { datum: ChartDatum; swing: OddsSwing }[];
  ticks: { x: number; label: string; major: boolean }[];
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

/** "Sun 8:30a" / "12p" — compact clock labels for the axis. */
export function axisClock(ms: number, withDay: boolean): string {
  const d = new Date(ms);
  const h = d.getHours();
  const m = d.getMinutes();
  const hh = h % 12 === 0 ? 12 : h % 12;
  const ap = h < 12 ? "a" : "p";
  const time = m ? `${hh}:${String(m).padStart(2, "0")}${ap}` : `${hh}${ap}`;
  return withDay ? `${d.toLocaleDateString([], { weekday: "short" })} ${time}` : time;
}

/** Axis ticks: each window's start (with its day), then every hour on the
 * hour, dropping any that would sit closer than `minGapX` to a kept one. */
function buildTicks(windows: GameWindow[], minGapX: number) {
  const ticks: { x: number; label: string; major: boolean }[] = [];
  for (const w of windows) {
    ticks.push({ x: w.offset, label: axisClock(w.start, true), major: true });
    const first = Math.ceil((w.start + 1) / HOUR) * HOUR;
    for (let t = first; t < w.end; t += HOUR) {
      ticks.push({ x: w.offset + (t - w.start), label: axisClock(t, false), major: false });
    }
  }
  const kept: typeof ticks = [];
  for (const t of ticks.filter((t) => t.major)) {
    if (!kept.some((k) => Math.abs(k.x - t.x) < minGapX)) kept.push(t);
  }
  for (const t of ticks.filter((t) => !t.major)) {
    if (!kept.some((k) => Math.abs(k.x - t.x) < minGapX)) kept.push(t);
  }
  return kept.sort((a, b) => a.x - b.x);
}

export function buildTimeline(
  history: OddsHistory,
  now: number,
  view: TimelineView,
  plotWidthPx: number,
  minTickGapPx = 46,
): Timeline {
  const kicks = (history.kickoffs ?? [])
    .map((k) => parseUtc(k.t))
    .filter((t): t is number => t != null)
    .sort((a, b) => a - b);
  let raw = (history.windows ?? [])
    .map((w) => ({ start: parseUtc(w.start), end: parseUtc(w.end) }))
    .filter((w): w is { start: number; end: number } => w.start != null && w.end != null);

  const pts = history.points
    .map((p) => ({ p, t: parseUtc(p.t) }))
    .filter((x): x is { p: OddsPoint; t: number } => x.t != null)
    .sort((a, b) => a.t - b.t);
  if (!raw.length && pts.length) {
    raw = [{ start: pts[0].t, end: Math.max(pts[pts.length - 1].t, pts[0].t + MIN) }];
  }
  if (view === "today") raw = raw.filter((w) => sameLocalDay(w.start, now) || sameLocalDay(w.end, now));
  const windows = finishWindows(raw, kicks);
  const empty: Timeline = { windows, data: [], end: 0, swings: [], ticks: [] };
  if (!windows.length) return empty;

  const first = windows[0].start;
  const last = windows[windows.length - 1].end;
  // Today's view opens with the odds as they stood at today's first kickoff.
  const before = pts.filter((x) => x.t < first);
  const inView = pts.filter((x) => x.t >= first && x.t <= Math.max(last, now));
  const seed = view === "today" && before.length ? [before[before.length - 1]] : [];
  const data: ChartDatum[] = [
    ...seed.map(({ p }) => ({ x: 0, t: first, you: pct(p.win_probability), point: { ...p, swing: null, events: [] } })),
    ...inView.map(({ p, t }) => ({ x: toX(t, windows), t, you: pct(p.win_probability), point: p })),
  ];
  if (!data.length) return empty;
  data[data.length - 1] = { ...data[data.length - 1], now: true };
  const end = axisEnd(windows);
  const swings = data
    .filter((d) => d.point.swing)
    .map((d) => ({ datum: d, swing: d.point.swing! }));
  const minGapX = plotWidthPx > 0 ? (minTickGapPx / plotWidthPx) * end : end / 6;
  return { windows, data, end, swings, ticks: buildTicks(windows, minGapX) };
}

function pct(p: number): number {
  return Math.round(p * 1000) / 10;
}

/** "Gibbs" from "Jahmyr Gibbs", "St. Brown" from "Amon-Ra St. Brown";
 * team defenses keep their full name. */
export function shortName(c: Pick<OddsEvent, "name" | "position">): string {
  const pos = (c.position ?? "").toUpperCase();
  if (pos === "DEF" || pos === "DST" || pos === "D/ST") return c.name;
  const parts = c.name.trim().split(/\s+/);
  while (parts.length > 2 && /^(jr|sr|ii|iii|iv|v)\.?$/i.test(parts[parts.length - 1])) parts.pop();
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

const STATUS_SHORT: Record<string, string> = {
  "injured reserve": "IR",
  out: "Out",
  doubtful: "Doubtful",
  questionable: "Q",
  suspension: "Susp.",
};

/** Few-word tag for an event on the chart: "TD", "INT", "IR"… */
export function eventTag(e: OddsEvent): string {
  if (e.kind === "td") return "TD";
  if (e.kind === "turnover") return e.label === "INT" ? "INT" : "fumble";
  if (e.kind === "kick") return e.label.includes("FG") ? "FG" : "PAT";
  if (e.kind === "news") {
    const m = e.label.match(/→\s*([^,]+)/);
    const status = m?.[1]?.trim();
    return status ? (STATUS_SHORT[status.toLowerCase()] ?? status) : "news";
  }
  return e.label;
}

/** Chart label for a swing: "Gibbs TD +8%". */
export function swingLabel(s: OddsSwing): string {
  const d = s.drivers[0];
  if (!d) return `Update ${swingPct(s.delta)}`;
  return `${shortName(d)} ${eventTag(d)} ${swingPct(s.delta)}`;
}

/** Full description: "Brock Purdy 32-yd TD pass", "Jahmyr Gibbs +8.4 pts",
 * "Davante Adams → Injured Reserve, −16.6 proj". */
export function eventText(e: OddsEvent): string {
  return `${e.name} ${e.label}`;
}

export function fmtDayClock(ms: number): string {
  return new Date(ms).toLocaleString([], {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}
