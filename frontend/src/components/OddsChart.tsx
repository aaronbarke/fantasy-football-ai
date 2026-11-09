"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  buildTimeline,
  fmtClock,
  fmtDayClock,
  hasGamesToday,
  shortName,
  signed,
  swingLabel,
  swingPct,
  type ChartDatum,
  type OddsChange,
  type OddsHistory,
  type TimelineView,
} from "@/lib/oddsTimeline";

const UP = "#16a34a";
const DOWN = "#dc2626";
const LINE = "#3b6af0";
const MUTED = "#9ca3af";
// Below this chart width, swing labels drop off the chart (the dots stay; the
// list underneath carries the detail) so they don't pile on top of each other.
const LABEL_MIN_WIDTH = 520;
const LIST_PREVIEW = 4;
// At most this many swings get a text label on the chart, biggest first, and
// never two closer than LABEL_GAP_PX on the same side of the line.
const MAX_LABELS = 6;
const LABEL_GAP_PX = 74;
// Plot area = chart width minus the y-axis and right margin.
const PLOT_INSET_PX = 52;

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function ChangeChip({ c }: { c: OddsChange }) {
  const helped = c.side === "user" ? c.delta > 0 : c.delta < 0;
  return (
    <span className="whitespace-nowrap">
      <span className="font-semibold text-gray-800 dark:text-gray-200">{shortName(c)}</span>
      {c.side === "opp" && (
        <span className="ml-0.5 text-[10px] uppercase text-gray-400">opp</span>
      )}{" "}
      <span
        className={`tabular-nums ${helped ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
      >
        {signed(c.delta)}
      </span>
    </span>
  );
}

function OddsTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: ChartDatum }[];
}) {
  const d = payload?.[0]?.payload;
  if (!active || !d) return null;
  const p = d.point;
  const swing = p?.swing;
  const changes = swing?.drivers.length ? swing.drivers : (p?.changes ?? []).slice(0, 3);
  return (
    <div className="max-w-[220px] rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md dark:border-gray-700 dark:bg-gray-900">
      <p className="text-gray-400">{p ? fmtDayClock(d.t) : "Now"}</p>
      <p className="font-semibold text-gray-900 dark:text-gray-100">
        {d.you.toFixed(0)}% to win
        {swing && (
          <span
            className="ml-1.5 tabular-nums"
            style={{ color: swing.delta > 0 ? UP : DOWN }}
          >
            {swingPct(swing.delta)}
          </span>
        )}
      </p>
      {p && p.user_points != null && p.opp_points != null && (
        <p className="tabular-nums text-gray-500">
          {p.user_points.toFixed(1)} – {p.opp_points.toFixed(1)}
        </p>
      )}
      {changes.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
          {changes.map((c) => (
            <ChangeChip key={c.id} c={c} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function OddsChart({ history }: { history: OddsHistory }) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [now, setNow] = useState(() => Date.now());
  // Keep "now" (the right edge) moving even between data refreshes.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => setNow(Date.now()), [history]);

  const today = hasGamesToday(history, now);
  const [picked, setPicked] = useState<TimelineView | null>(null);
  const view: TimelineView = picked ?? "week";
  const [showAll, setShowAll] = useState(false);

  const tl = useMemo(() => buildTimeline(history, now, view), [history, now, view]);
  const showLabels = width >= LABEL_MIN_WIDTH;

  // Pick which swings get a label: the biggest ones that have room.
  const labeled = useMemo(() => {
    const out = new Set<number>();
    if (!showLabels || tl.end <= 0) return out;
    const plot = Math.max(width - PLOT_INSET_PX, 1);
    const taken: { px: number; up: boolean }[] = [];
    const bySize = [...tl.swings].sort(
      (a, b) => Math.abs(b.swing.delta) - Math.abs(a.swing.delta),
    );
    for (const { datum, swing } of bySize) {
      if (out.size >= MAX_LABELS) break;
      const px = (datum.x / tl.end) * plot;
      const up = swing.delta > 0;
      if (taken.some((t) => t.up === up && Math.abs(t.px - px) < LABEL_GAP_PX)) continue;
      taken.push({ px, up });
      out.add(datum.t);
    }
    return out;
  }, [tl, width, showLabels]);

  if (tl.data.length < 2) return null;

  const ticks: number[] = [];
  const tickLabel = new Map<number, string>();
  tl.windows.forEach((w, i) => {
    w.slots.forEach((s, j) => {
      const x = w.offset + (s - w.start);
      ticks.push(x);
      // Each window's first marker names the day; the rest just the time.
      tickLabel.set(
        x,
        j === 0 && (view === "week" || i > 0)
          ? new Date(s).toLocaleString([], { weekday: "short", hour: "numeric" })
          : fmtClock(s).replace(/:00(?=\s|$)/, ""),
      );
    });
  });

  const swingsNewestFirst = [...tl.swings].reverse();
  const listed = showAll ? swingsNewestFirst : swingsNewestFirst.slice(0, LIST_PREVIEW);
  const threshold = Math.round((history.swing_threshold ?? 0.05) * 100);

  return (
    <div className="mt-6" ref={ref}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-400">
          Your win probability{view === "today" ? " today" : " this week"}
        </p>
        {today && (
          <div
            role="group"
            aria-label="Chart range"
            className="flex rounded-md border border-gray-200 p-0.5 text-[11px] font-semibold dark:border-gray-700"
          >
            {(["week", "today"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setPicked(v)}
                className={`rounded px-2 py-0.5 ${
                  view === v
                    ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                    : "text-gray-500"
                }`}
              >
                {v === "week" ? "Week" : "Today"}
              </button>
            ))}
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={showLabels ? 210 : 170}>
        <LineChart
          data={tl.data}
          margin={{ top: showLabels ? 20 : 8, right: 12, bottom: 0, left: -18 }}
        >
          <ReferenceLine y={50} stroke="#a1a1aa" strokeDasharray="3 3" />
          {/* Where the real-time gap between game windows was cut out. */}
          {tl.windows.slice(1).map((w) => (
            <ReferenceLine key={`gap-${w.start}`} x={w.offset} stroke={MUTED} strokeWidth={1.5} />
          ))}
          {ticks.map((x) => (
            <ReferenceLine
              key={`k-${x}`}
              x={x}
              stroke={MUTED}
              strokeOpacity={0.45}
              strokeDasharray="2 3"
            />
          ))}
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, tl.end]}
            ticks={ticks}
            tickFormatter={(x: number) => tickLabel.get(x) ?? ""}
            interval="preserveStart"
            minTickGap={10}
            tick={{ fontSize: 10, fill: MUTED }}
            stroke={MUTED}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fontSize: 10, fill: MUTED }}
            stroke={MUTED}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<OddsTooltip />} />
          <Line
            type="linear"
            dataKey="you"
            stroke={LINE}
            strokeWidth={2}
            isAnimationActive={false}
            activeDot={{ r: 4 }}
            dot={(props: { cx?: number; cy?: number; index?: number; payload?: ChartDatum }) => {
              const { cx, cy, payload, index } = props;
              const swing = payload?.point?.swing;
              if (!swing || cx == null || cy == null) return <g key={`d-${index}`} />;
              const color = swing.delta > 0 ? UP : DOWN;
              const above = swing.delta > 0 ? cy > 28 : cy > 160;
              const withLabel = labeled.has(payload!.t);
              return (
                <g key={`d-${index}`}>
                  <circle
                    cx={cx}
                    cy={cy}
                    r={withLabel ? 4.5 : 3}
                    fill={color}
                    stroke="#fff"
                    strokeWidth={1.5}
                  />
                  {withLabel && (
                    <text
                      x={cx}
                      y={above ? cy - 9 : cy + 16}
                      textAnchor={cx > width - 70 ? "end" : cx < 70 ? "start" : "middle"}
                      fontSize={10}
                      fontWeight={600}
                      fill={color}
                    >
                      {swingLabel(swing)}
                    </text>
                  )}
                </g>
              );
            }}
          />
        </LineChart>
      </ResponsiveContainer>

      <div className="mt-3">
        <p className="text-xs font-semibold text-gray-400">
          Big swings <span className="font-normal">({threshold}+ pts)</span>
        </p>
        {tl.swings.length === 0 ? (
          <p className="mt-1 text-xs text-gray-400">
            No big swings {view === "today" ? "today" : "this week"} yet.
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-gray-100 dark:divide-gray-800">
            {listed.map(({ datum, swing }) => (
              <li key={datum.t} className="flex items-start gap-2 py-1.5 text-xs">
                <span
                  className="w-10 shrink-0 rounded px-1 py-0.5 text-center font-bold tabular-nums text-white"
                  style={{ background: swing.delta > 0 ? UP : DOWN }}
                >
                  {swingPct(swing.delta)}
                </span>
                <span className="min-w-0 flex-1 flex-wrap gap-x-2 text-gray-500">
                  {swing.drivers.length ? (
                    swing.drivers.map((c, i) => (
                      <span key={c.id}>
                        {i > 0 && ", "}
                        <ChangeChip c={c} />
                      </span>
                    ))
                  ) : (
                    <span>Projection update (injury news or lineup change)</span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-gray-400">
                  {fmtDayClock(datum.t)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {tl.swings.length > LIST_PREVIEW && (
          <button
            type="button"
            onClick={() => setShowAll((s) => !s)}
            className="mt-1 text-xs font-semibold text-accent-ink"
          >
            {showAll ? "Show fewer" : `Show all ${tl.swings.length}`}
          </button>
        )}
      </div>
    </div>
  );
}
