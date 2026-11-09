"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Area,
  ComposedChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  buildTimeline,
  eventText,
  fmtDayClock,
  hasGamesToday,
  parseUtc,
  signed,
  swingLabel,
  swingPct,
  type ChartDatum,
  type OddsEvent,
  type OddsHistory,
  type TimelineView,
} from "@/lib/oddsTimeline";

const UP = "#16a34a";
const DOWN = "#dc2626";
const MUTED = "#9ca3af";
// The card's own background, so labels and dots get a halo in either theme.
const SURFACE = "rgb(var(--surface))";
// Below this chart width, swing labels drop off the chart (the dots stay; the
// list underneath carries the detail) so they don't pile on top of each other.
const LABEL_MIN_WIDTH = 520;
const LIST_PREVIEW = 5;
// At most this many swings get a text label on the chart, biggest first, and
// never two closer than LABEL_GAP_PX on the same side of the line.
const MAX_LABELS = 6;
const LABEL_GAP_PX = 96;
// Plot area = chart width minus the y-axis and right margin.
const PLOT_INSET_PX = 56;

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

function helped(e: OddsEvent): boolean {
  return e.side === "user" ? e.pts > 0 : e.pts < 0;
}

function EventLine({ e }: { e: OddsEvent }) {
  return (
    <span className="whitespace-nowrap">
      <span className="font-semibold text-gray-800 dark:text-gray-200">{eventText(e)}</span>
      {e.side === "opp" && (
        <span className="ml-1 rounded bg-gray-100 px-1 text-[9px] font-bold uppercase text-gray-500 dark:bg-gray-800">
          opp
        </span>
      )}
      {e.kind !== "news" && (
        <span
          className={`ml-1 tabular-nums ${helped(e) ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
        >
          {signed(e.pts)}
        </span>
      )}
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
  const events = p.swing?.drivers.length ? p.swing.drivers : (p.events ?? []).slice(0, 4);
  const delta = p.swing?.delta ?? p.delta ?? null;
  return (
    <div className="max-w-[240px] rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-md dark:border-gray-700 dark:bg-gray-900">
      <p className="text-gray-400">{d.now ? `Now · ${fmtDayClock(d.t)}` : fmtDayClock(d.t)}</p>
      <p className="font-semibold text-gray-900 dark:text-gray-100">
        {d.you.toFixed(0)}% to win
        {delta != null && Math.abs(delta) >= 0.005 && (
          <span className="ml-1.5 tabular-nums" style={{ color: delta > 0 ? UP : DOWN }}>
            {swingPct(delta)}
          </span>
        )}
      </p>
      {p.user_points != null && p.opp_points != null && (
        <p className="tabular-nums text-gray-500">
          You {p.user_points.toFixed(1)} – {p.opp_points.toFixed(1)}
        </p>
      )}
      {events.length > 0 && (
        <div className="mt-1 space-y-0.5">
          {events.map((e, i) => (
            <div key={`${e.id}-${i}`}>
              <EventLine e={e} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OddsChart({ history }: { history: OddsHistory }) {
  const gradId = useId().replace(/:/g, "");
  const { ref, width } = useWidth<HTMLDivElement>();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => setNow(Date.now()), [history]);

  const today = hasGamesToday(history, now);
  const [view, setView] = useState<TimelineView>("week");
  const [showAll, setShowAll] = useState(false);
  const plot = Math.max(width - PLOT_INSET_PX, 1);
  const tl = useMemo(
    () => buildTimeline(history, now, view, plot),
    [history, now, view, plot],
  );
  const showLabels = width >= LABEL_MIN_WIDTH;

  // Pick which swings get a label: the biggest ones that have room.
  const labeled = useMemo(() => {
    const out = new Set<number>();
    if (!showLabels || tl.end <= 0) return out;
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
  }, [tl, plot, showLabels]);

  // Split colour at 50%: green while you're favoured, red while you're not.
  const { lineSplit, areaSplit } = useMemo(() => {
    const ys = tl.data.map((d) => d.you);
    const hi = Math.max(...ys, 0);
    const lo = Math.min(...ys, 100);
    const lineSplit = hi === lo ? (hi >= 50 ? 1 : 0) : Math.min(1, Math.max(0, (hi - 50) / (hi - lo)));
    const ahi = Math.max(hi, 50);
    const alo = Math.min(lo, 50);
    const areaSplit = ahi === alo ? 0.5 : (ahi - 50) / (ahi - alo);
    return { lineSplit, areaSplit };
  }, [tl]);

  const threshold = Math.round((history.swing_threshold ?? 0.05) * 100);
  const head = (
    <div className="mb-1 flex items-center justify-between gap-2">
      <p className="text-xs font-semibold text-gray-400">
        Win probability{view === "today" ? " today" : " this week"}
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
              onClick={() => setView(v)}
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
  );

  if (tl.data.length < 2) {
    const start = parseUtc(history.window_start);
    return (
      <div className="mt-6" ref={ref}>
        {head}
        <div className="flex h-32 flex-col items-center justify-center rounded-xl border border-dashed border-gray-200 px-4 text-center dark:border-gray-800">
          <p className="text-sm font-semibold text-gray-600 dark:text-gray-300">
            {start && start > now ? "The chart starts at kickoff" : "No games yet"}
          </p>
          <p className="mt-1 text-xs text-gray-400">
            {start && start > now
              ? `Your odds will be tracked play by play from ${fmtDayClock(start)}.`
              : "Once your players' games start, every scoring play shows up here."}
          </p>
        </div>
      </div>
    );
  }

  const last = tl.data[tl.data.length - 1];
  const swingsNewestFirst = [...tl.swings].reverse();
  const listed = showAll ? swingsNewestFirst : swingsNewestFirst.slice(0, LIST_PREVIEW);
  const kickoffXs = tl.windows.flatMap((w) => w.kickoffs.map((k) => w.offset + (k - w.start)));

  return (
    <div className="mt-6" ref={ref}>
      {head}
      <ResponsiveContainer width="100%" height={showLabels ? 230 : 190}>
        <ComposedChart
          data={tl.data}
          margin={{ top: showLabels ? 22 : 10, right: 14, bottom: 0, left: -14 }}
        >
          <defs>
            <linearGradient id={`line-${gradId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset={0} stopColor={UP} />
              <stop offset={lineSplit} stopColor={UP} />
              <stop offset={lineSplit} stopColor={DOWN} />
              <stop offset={1} stopColor={DOWN} />
            </linearGradient>
            <linearGradient id={`area-${gradId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset={0} stopColor={UP} stopOpacity={0.28} />
              <stop offset={areaSplit} stopColor={UP} stopOpacity={0.06} />
              <stop offset={areaSplit} stopColor={DOWN} stopOpacity={0.06} />
              <stop offset={1} stopColor={DOWN} stopOpacity={0.28} />
            </linearGradient>
          </defs>
          {/* Cut-out dead time between game windows. */}
          {tl.windows.slice(1).map((w) => (
            <ReferenceLine key={`gap-${w.start}`} x={w.offset} stroke={MUTED} strokeWidth={2} strokeOpacity={0.6} />
          ))}
          {kickoffXs.map((x) => (
            <ReferenceLine key={`k-${x}`} x={x} stroke={MUTED} strokeOpacity={0.5} strokeDasharray="2 3" />
          ))}
          <ReferenceLine y={50} stroke={MUTED} strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            domain={[0, tl.end]}
            ticks={tl.ticks.map((t) => t.x)}
            interval={0}
            tickFormatter={(x: number) => tl.ticks.find((t) => t.x === x)?.label ?? ""}
            tick={{ fontSize: 10, fill: MUTED }}
            stroke={MUTED}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            tick={{ fontSize: 10, fill: MUTED }}
            stroke={MUTED}
            tickLine={false}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<OddsTooltip />} cursor={{ stroke: MUTED, strokeDasharray: "2 2" }} />
          <Area
            type="linear"
            dataKey="you"
            baseValue={50}
            stroke={`url(#line-${gradId})`}
            strokeWidth={2}
            fill={`url(#area-${gradId})`}
            isAnimationActive={false}
            activeDot={{ r: 4 }}
            dot={false}
          />
          {tl.swings.map(({ datum, swing }) => {
            const color = swing.delta > 0 ? UP : DOWN;
            const withLabel = labeled.has(datum.t);
            return (
              <ReferenceDot
                key={`s-${datum.t}`}
                x={datum.x}
                y={datum.you}
                r={withLabel ? 4.5 : 3}
                fill={color}
                stroke={SURFACE}
                strokeWidth={1.5}
                ifOverflow="visible"
                label={
                  withLabel
                    ? {
                        value: swingLabel(swing),
                        position: swing.delta > 0 ? (datum.you > 88 ? "bottom" : "top") : datum.you < 12 ? "top" : "bottom",
                        fontSize: 10,
                        fontWeight: 600,
                        fill: color,
                        stroke: SURFACE,
                        strokeWidth: 3,
                        paintOrder: "stroke",
                        offset: 8,
                      }
                    : undefined
                }
              />
            );
          })}
          {/* Where things stand right now. */}
          <ReferenceDot
            x={last.x}
            y={last.you}
            r={5}
            fill={last.you >= 50 ? UP : DOWN}
            stroke={SURFACE}
            strokeWidth={2}
            ifOverflow="visible"
            label={{
              value: `${Math.round(last.you)}%`,
              position: last.you > 85 ? "bottom" : "top",
              fontSize: 11,
              fontWeight: 700,
              fill: last.you >= 50 ? UP : DOWN,
              stroke: SURFACE,
              strokeWidth: 3,
              paintOrder: "stroke",
              offset: 8,
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      {history.source === "estimate" && (
        <p className="mt-1 text-[11px] text-gray-400">
          Play-by-play isn&apos;t available right now, so points are spread evenly over each game.
        </p>
      )}

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
                  className="w-11 shrink-0 rounded px-1 py-0.5 text-center font-bold tabular-nums text-white"
                  style={{ background: swing.delta > 0 ? UP : DOWN }}
                >
                  {swingPct(swing.delta)}
                </span>
                <span className="min-w-0 flex-1 space-y-0.5 text-gray-500">
                  {swing.drivers.length ? (
                    swing.drivers.map((e, i) => (
                      <span key={`${e.id}-${i}`} className="block">
                        <EventLine e={e} />
                      </span>
                    ))
                  ) : (
                    <span>Projection update</span>
                  )}
                  {datum.point.user_points != null && datum.point.opp_points != null && (
                    <span className="block tabular-nums text-[11px] text-gray-400">
                      You {datum.point.user_points.toFixed(1)} – {datum.point.opp_points.toFixed(1)}
                    </span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-gray-400">{fmtDayClock(datum.t)}</span>
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
