"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Ruler, Target, UserCheck } from "lucide-react";
import Navbar from "@/components/Navbar";
import PageHeader from "@/components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/PageState";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";

interface ErrorStats {
  count: number;
  avg_miss: number;
  bias: number;
  rmse: number;
  within_range_pct: number | null;
}

interface LineupChange {
  started: string | null;
  started_points: number | null;
  instead_of: string | null;
  instead_points: number | null;
}

interface LineupWeek {
  week: number;
  correct: number;
  slots: number;
  recommended_points: number;
  best_points: number;
  your_points: number | null;
  should_have_started: string[];
  should_have_sat: string[];
  followed_our_lineup: boolean | null;
  your_changes: LineupChange[] | null;
}

interface TrackRecord {
  season: number;
  scoring: string;
  weeks_tracked: number[];
  pending_weeks: number[];
  projections: {
    overall: ErrorStats | null;
    by_position: Record<string, ErrorStats | null>;
    vs_sleeper: {
      count: number;
      ours: number | null;
      sleeper_only: number | null;
      our_model_only: number | null;
    };
    calibration?: {
      by_position: Record<
        string,
        { pct: number; observed_pct: number; games: number; weeks: number }
      >;
      count: number;
      with: number | null;
      without: number | null;
    };
    your_players: {
      id: string;
      name: string;
      position: string | null;
      games: number;
      avg_projected: number;
      avg_actual: number;
      avg_miss: number;
      bias: number;
    }[];
    biggest_misses: {
      week: number;
      name: string;
      position: string | null;
      projected: number;
      actual: number;
    }[];
  };
  lineups: {
    totals: {
      weeks: number;
      correct: number;
      slots: number;
      perfect_weeks: number;
      avg_points_left: number;
      weeks_with_your_lineup: number;
      weeks_followed: number;
      avg_your_changes_net: number | null;
    } | null;
    weeks: LineupWeek[];
  };
  start_sit: {
    game_plan: {
      wins: number;
      losses: number;
      ties: number;
      calls: {
        week: number;
        start: string;
        sit: string;
        start_points: number;
        sit_points: number;
        result: "win" | "loss" | "tie";
      }[];
    };
    chat: { wins: number; losses: number; ties: number; pending: number };
  };
}

/* ── Plain-language helpers ─────────────────────────────────────────────── */

type Tone = "good" | "ok" | "bad" | "neutral";

interface Verdict {
  tone: Tone;
  label: string;
}

const toneClass: Record<Tone, string> = {
  good: "tone-emerald",
  ok: "tone-amber",
  bad: "tone-rose",
  neutral: "tone-sky",
};

function pct(n: number, d: number): number {
  return d ? Math.round((100 * n) / d) : 0;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function record(w: number, l: number, t: number): string {
  return t ? `${w}–${l}–${t}` : `${w}–${l}`;
}

function pts(n: number): string {
  return n.toFixed(1);
}

/** Bias is actual minus projected: positive means players outscored us. */
function leanText(bias: number): string {
  if (Math.abs(bias) < 0.3) return "No real lean high or low";
  return bias > 0
    ? `Runs ${pts(bias)} pts low (players scored a bit more)`
    : `Runs ${pts(Math.abs(bias))} pts high (players scored a bit less)`;
}

function lineupVerdict(correct: number, slots: number, weeks: number): Verdict {
  if (weeks < 3) return { tone: "neutral", label: "Early days" };
  const p = pct(correct, slots);
  if (p >= 90) return { tone: "good", label: "Strong" };
  if (p >= 80) return { tone: "ok", label: "Solid" };
  return { tone: "bad", label: "Room to improve" };
}

function startSitVerdict(w: number, l: number): Verdict {
  if (w + l < 5) return { tone: "neutral", label: "Too early to tell" };
  const p = pct(w, w + l);
  if (p >= 60) return { tone: "good", label: "Strong" };
  if (p >= 50) return { tone: "ok", label: "Slightly better than a coin flip" };
  return { tone: "bad", label: "Worse than a coin flip" };
}

function projectionVerdict(ours: number | null, sleeper: number | null): Verdict | null {
  if (ours == null || sleeper == null) return null;
  const gap = sleeper - ours;
  if (gap >= 0.2) return { tone: "good", label: "Better than Sleeper" };
  if (gap > -0.2) return { tone: "ok", label: "Even with Sleeper" };
  return { tone: "bad", label: "Behind Sleeper" };
}

/* ── Building blocks ───────────────────────────────────────────────────── */

function Pill({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className={`tone-chip ${toneClass[verdict.tone]} px-2 py-0.5 text-[11px] font-semibold`}
    >
      {verdict.label}
    </span>
  );
}

function Headline({
  icon,
  tone,
  label,
  value,
  summary,
  verdict,
  explain,
}: {
  icon: ReactNode;
  tone: string;
  label: string;
  value: ReactNode;
  summary: ReactNode;
  verdict?: Verdict | null;
  explain: ReactNode;
}) {
  return (
    <div className={`flex flex-col rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-800 ${tone}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-sm font-medium text-gray-600 dark:text-gray-300">
          <span className="tone-chip h-7 w-7">{icon}</span>
          {label}
        </span>
        {verdict && <Pill verdict={verdict} />}
      </div>
      <p className="mt-4 text-3xl font-semibold tabular-nums tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-gray-700 dark:text-gray-200">{summary}</p>
      <p className="mt-3 border-t border-gray-100 pt-3 text-xs leading-5 text-gray-500 dark:border-gray-800">
        {explain}
      </p>
    </div>
  );
}

function Section({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mt-10">
      <h2 className="text-base font-semibold">{title}</h2>
      {intro && <p className="mt-1 max-w-2xl text-sm text-gray-500">{intro}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** What the track-record calibration is doing to this position right now. */
function CalibrationLine({
  cal,
  position,
}: {
  cal?: { pct: number; observed_pct: number; weeks: number };
  position: string;
}) {
  const pct = cal ? Math.round(cal.pct * 1000) / 10 : 0;
  return (
    <p className="mt-2 border-t border-gray-100 pt-2 text-xs leading-5 text-gray-600 dark:border-gray-800 dark:text-gray-300">
      {!cal
        ? "Not enough graded weeks yet to adjust."
        : pct === 0
          ? `On target lately, so no adjustment.`
          : `New ${position} projections ${pct > 0 ? "raised" : "lowered"} ${Math.abs(pct)}% (they ran ${Math.round(Math.abs(cal.observed_pct) * 100)}% ${cal.observed_pct > 0 ? "low" : "high"} over the last ${cal.weeks} weeks).`}
    </p>
  );
}

function StarterDots({ correct, slots }: { correct: number; slots: number }) {
  return (
    <span className="flex gap-1" aria-hidden="true">
      {Array.from({ length: slots }, (_, i) => (
        <span
          key={i}
          className={`h-2 w-2 rounded-full ${i < correct ? "bg-emerald-500" : "bg-gray-300 dark:bg-gray-700"}`}
        />
      ))}
    </span>
  );
}

function WeekRow({ w }: { w: LineupWeek }) {
  const lost = w.best_points - w.recommended_points;
  const perfect = w.correct === w.slots;
  const net = w.your_points != null ? w.your_points - w.recommended_points : null;
  return (
    <li className="rounded-xl border border-gray-200 bg-white px-4 py-3 dark:border-gray-800">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3">
          <span className="w-16 text-sm font-semibold">Week {w.week}</span>
          <StarterDots correct={w.correct} slots={w.slots} />
          <span className="text-sm text-gray-600 dark:text-gray-300">
            {w.correct} of {w.slots} right
          </span>
        </div>
        {perfect ? (
          <Pill verdict={{ tone: "good", label: "Best possible lineup" }} />
        ) : (
          <Pill verdict={{ tone: "ok", label: `${pts(lost)} pts short of best` }} />
        )}
      </div>
      <dl className="mt-3 grid grid-cols-[5.5rem_1fr] gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[7rem_1fr]">
        <dt className="text-gray-500">Our lineup</dt>
        <dd className="tabular-nums">
          {pts(w.recommended_points)} pts
          <span className="text-gray-500"> · best possible {pts(w.best_points)}</span>
        </dd>
        {!perfect && (
          <>
            <dt className="text-gray-500">We missed</dt>
            <dd>
              Should have started {w.should_have_started.join(", ")} over{" "}
              {w.should_have_sat.join(", ")}
            </dd>
          </>
        )}
        {w.your_points != null && (
          <>
            <dt className="text-gray-500">You</dt>
            <dd>
              {w.followed_our_lineup ? (
                <>Played our lineup ({pts(w.your_points)} pts)</>
              ) : (
                <>
                  <span className="tabular-nums">{pts(w.your_points)} pts</span>
                  {net != null && Math.abs(net) >= 0.05 && (
                    <span
                      className={
                        net > 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-rose-600 dark:text-rose-400"
                      }
                    >
                      {" "}
                      ({net > 0 ? "+" : "−"}
                      {pts(Math.abs(net))} vs ours)
                    </span>
                  )}
                  {w.your_changes?.map((c, i) => (
                    <span key={i} className="block text-xs text-gray-500">
                      {c.started
                        ? `Started ${c.started} (${c.started_points ?? "—"}) instead of ${c.instead_of ?? "our pick"}${c.instead_points != null ? ` (${c.instead_points})` : ""}`
                        : `Left ${c.instead_of} (${c.instead_points}) on the bench`}
                    </span>
                  ))}
                </>
              )}
            </dd>
          </>
        )}
      </dl>
    </li>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function AccuracyPage() {
  const { league } = useLeague();
  const [allCalls, setAllCalls] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["accuracy", league?.id],
    queryFn: () => api<TrackRecord>(`/api/accuracy/${league!.id}`),
    enabled: !!league,
  });

  const overall = data?.projections.overall ?? null;
  const lineups = data?.lineups.totals ?? null;
  const gp = data?.start_sit.game_plan;
  const chat = data?.start_sit.chat;
  const vs = data?.projections.vs_sleeper;
  const cal = data?.projections.calibration;
  const nothingTracked = data && data.weeks_tracked.length === 0;
  const waiting = data && !nothingTracked && !overall && !lineups;
  const gpDecided = gp ? gp.wins + gp.losses : 0;
  const chatDecided = chat ? chat.wins + chat.losses + chat.ties : 0;
  const calls = gp ? (allCalls ? gp.calls : gp.calls.slice(0, 6)) : [];

  return (
    <>
      <Navbar />
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-5xl px-4 py-8">
        <PageHeader
          eyebrow="How our advice held up"
          title="Track record"
          description="Before each game we save our projections and the lineup we recommend. After the game we check them against what actually happened."
        />

        {isLoading && <LoadingState label="Checking our picks…" />}
        {error && <ErrorState retry={() => void refetch()} />}

        {nothingTracked && (
          <EmptyState
            title="Tracking starts this week"
            description="We save projections and your recommended lineup before each game and grade them once the stats are in, usually by Tuesday morning."
          />
        )}
        {waiting && (
          <EmptyState
            title={`Week ${data!.pending_weeks.join(", ")} is in progress`}
            description="Results show up once the games are over and the stats are in, usually by Tuesday morning."
          />
        )}

        {data && (overall || lineups) && (
          <>
            {data.pending_weeks.length > 0 && (
              <p className="mt-4 text-xs text-gray-500">
                Week {data.pending_weeks.join(", ")} isn&apos;t graded yet. It&apos;ll show up
                once the games are final.
              </p>
            )}

            {/* ── The short version ── */}
            <Section title="The short version">
              <div className="grid gap-3 md:grid-cols-2">
                {lineups && (
                  <Headline
                    icon={<Target className="h-4 w-4" />}
                    tone="tone-blue"
                    label="Lineup picks"
                    value={`${pct(lineups.correct, lineups.slots)}%`}
                    summary={
                      <>
                        We picked {lineups.correct} of {lineups.slots} starters right over{" "}
                        {plural(lineups.weeks, "week")}.
                      </>
                    }
                    verdict={lineupVerdict(lineups.correct, lineups.slots, lineups.weeks)}
                    explain={
                      <>
                        Each week we compare our recommended lineup with the best lineup your
                        roster could have started, knowing the final scores.{" "}
                        {lineups.perfect_weeks > 0 &&
                          `${plural(lineups.perfect_weeks, "week")} were perfect. `}
                        On average we left {pts(lineups.avg_points_left)} pts a week on your
                        bench.
                      </>
                    }
                  />
                )}
                {gp && (
                  <Headline
                    icon={<ArrowLeftRight className="h-4 w-4" />}
                    tone="tone-violet"
                    label="Start/sit calls"
                    value={gpDecided ? `${pct(gp.wins, gpDecided)}%` : "—"}
                    summary={
                      gpDecided ? (
                        <>
                          Right {gp.wins} of {gpDecided} times ({record(gp.wins, gp.losses, gp.ties)}).
                        </>
                      ) : (
                        "No close calls graded yet."
                      )
                    }
                    verdict={gpDecided ? startSitVerdict(gp.wins, gp.losses) : null}
                    explain={
                      <>
                        When two of your players were close, we picked one to start. A call is
                        right if that player outscored the one we benched.
                        {chat && chatDecided > 0 &&
                          ` Picks from chat: ${record(chat.wins, chat.losses, chat.ties)}.`}
                      </>
                    }
                  />
                )}
                {overall && (
                  <Headline
                    icon={<Ruler className="h-4 w-4" />}
                    tone="tone-amber"
                    label="Projections"
                    value={`±${pts(overall.avg_miss)} pts`}
                    summary={
                      vs?.ours != null && vs.sleeper_only != null ? (
                        <>
                          Average miss per player. Sleeper&apos;s numbers alone missed by{" "}
                          {pts(vs.sleeper_only)}.
                        </>
                      ) : (
                        "Average miss per player, per game."
                      )
                    }
                    verdict={projectionVerdict(vs?.ours ?? null, vs?.sleeper_only ?? null)}
                    explain={
                      <>
                        Lower is better. One game swings a lot, so missing by a few points is
                        normal. {leanText(overall.bias)}.
                      </>
                    }
                  />
                )}
                {lineups && lineups.weeks_with_your_lineup > 0 && (
                  <Headline
                    icon={<UserCheck className="h-4 w-4" />}
                    tone="tone-emerald"
                    label="Your changes"
                    value={
                      lineups.weeks_followed === lineups.weeks_with_your_lineup ||
                      lineups.avg_your_changes_net == null
                        ? `${lineups.weeks_followed} of ${lineups.weeks_with_your_lineup}`
                        : `${lineups.avg_your_changes_net >= 0 ? "+" : "−"}${pts(Math.abs(lineups.avg_your_changes_net))} pts`
                    }
                    summary={
                      lineups.weeks_followed === lineups.weeks_with_your_lineup ? (
                        "You played our lineup every week."
                      ) : (
                        <>
                          Per week, on average, from changing our lineup. You played it as
                          recommended in {lineups.weeks_followed} of{" "}
                          {plural(lineups.weeks_with_your_lineup, "week")}.
                        </>
                      )
                    }
                    verdict={
                      lineups.avg_your_changes_net == null ||
                      lineups.weeks_followed === lineups.weeks_with_your_lineup
                        ? null
                        : Math.abs(lineups.avg_your_changes_net) < 0.5
                          ? { tone: "neutral", label: "About even" }
                          : lineups.avg_your_changes_net > 0
                            ? { tone: "good", label: "Your changes helped" }
                            : { tone: "ok", label: "Our lineup scored more" }
                    }
                    explain="Your actual lineup compared with the one we recommended. A plus means your swaps scored more than ours would have."
                  />
                )}
              </div>
            </Section>

            {/* ── Detail ── */}
            {data.lineups.weeks.length > 0 && (
              <Section
                title="Week by week"
                intro="Green dots are starters we got right. The best possible lineup uses the final scores, so it's a high bar."
              >
                <ul className="space-y-2">
                  {[...data.lineups.weeks].reverse().map((w) => (
                    <WeekRow key={w.week} w={w} />
                  ))}
                </ul>
              </Section>
            )}

            {gp && gp.calls.length > 0 && (
              <Section
                title="Start/sit calls"
                intro="Each close call from your game plan, newest first, with what both players scored."
              >
                <ul className="space-y-1.5">
                  {calls.map((c, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm dark:border-gray-800"
                    >
                      <span className="min-w-0">
                        <span className="text-gray-500">Week {c.week}: </span>
                        Start <strong className="font-semibold">{c.start}</strong> over{" "}
                        <strong className="font-semibold">{c.sit}</strong>
                        <span className="block text-xs tabular-nums text-gray-500">
                          {pts(c.start_points)} pts vs {pts(c.sit_points)} pts
                        </span>
                      </span>
                      <Pill
                        verdict={
                          c.result === "win"
                            ? { tone: "good", label: "Right" }
                            : c.result === "loss"
                              ? { tone: "bad", label: "Wrong" }
                              : { tone: "neutral", label: "Tie" }
                        }
                      />
                    </li>
                  ))}
                </ul>
                {gp.calls.length > 6 && (
                  <button
                    onClick={() => setAllCalls(!allCalls)}
                    className="mt-3 text-sm font-medium text-accent-ink hover:underline"
                  >
                    {allCalls ? "Show fewer" : `Show all ${gp.calls.length}`}
                  </button>
                )}
              </Section>
            )}

            {overall && (
              <Section
                title="Projections by position"
                intro={
                  <>
                    How far off our projections were, across every player we tracked (not just
                    your roster). When a position keeps running high or low, we nudge its new
                    projections to match.
                    {cal && cal.count > 0 && cal.with != null && cal.without != null && (
                      <>
                        {" "}
                        So far that{" "}
                        {cal.with < cal.without
                          ? `helped: average miss ${pts(cal.with)} with the nudge vs ${pts(cal.without)} without`
                          : cal.with > cal.without
                            ? `hurt: average miss ${pts(cal.with)} with the nudge vs ${pts(cal.without)} without`
                            : "made no difference"}{" "}
                        ({plural(cal.count, "projection")}).
                      </>
                    )}
                  </>
                }
              >
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {(["QB", "RB", "WR", "TE"] as const).map((pos) => {
                    const s = data.projections.by_position[pos];
                    if (!s) return null;
                    return (
                      <div
                        key={pos}
                        className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800"
                      >
                        <div className="flex items-center justify-between">
                          <span
                            className={`inline-flex h-6 w-8 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(pos)}`}
                          >
                            {pos}
                          </span>
                          <span className="text-xs text-gray-500">
                            {s.count.toLocaleString()} games
                          </span>
                        </div>
                        <p className="mt-3 text-2xl font-semibold tabular-nums">
                          ±{pts(s.avg_miss)}
                          <span className="ml-1 text-sm font-normal text-gray-500">pts off</span>
                        </p>
                        <p className="mt-1 text-xs leading-5 text-gray-500">{leanText(s.bias)}</p>
                        {s.within_range_pct != null && (
                          <p className="mt-1 text-xs leading-5 text-gray-500">
                            {s.within_range_pct}% landed inside our floor-to-ceiling range
                          </p>
                        )}
                        <CalibrationLine cal={cal?.by_position[pos]} position={pos} />
                      </div>
                    );
                  })}
                </div>
              </Section>
            )}

            {data.projections.your_players.length > 0 && (
              <Section
                title="Your players"
                intro="What we projected for each of your players, on average, and what they actually scored."
              >
                <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white dark:border-gray-800">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs font-medium text-gray-500">
                        <th className="px-3 py-2">Player</th>
                        <th className="hidden px-3 py-2 sm:table-cell">Games</th>
                        <th className="px-3 py-2 text-right">Projected</th>
                        <th className="px-3 py-2 text-right">Scored</th>
                        <th className="px-3 py-2 text-right">Off by</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.projections.your_players.map((p) => (
                        <tr key={p.id} className="border-t border-gray-100 tabular-nums dark:border-gray-800">
                          <td className="px-3 py-2 font-medium">
                            {p.name}
                            <span className="ml-1.5 text-xs font-normal text-gray-500">{p.position}</span>
                          </td>
                          <td className="hidden px-3 py-2 sm:table-cell">{p.games}</td>
                          <td className="px-3 py-2 text-right">{pts(p.avg_projected)}</td>
                          <td className="px-3 py-2 text-right">{pts(p.avg_actual)}</td>
                          <td className="px-3 py-2 text-right">±{pts(p.avg_miss)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            )}

            {data.projections.biggest_misses.length > 0 && (
              <Section title="Biggest misses on your players">
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {data.projections.biggest_misses.map((m, i) => {
                    const diff = m.actual - m.projected;
                    return (
                      <li
                        key={i}
                        className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-800"
                      >
                        <span className="min-w-0">
                          <span className="block truncate">
                            <span className="text-gray-500">Week {m.week}: </span>
                            {m.name}
                          </span>
                          <span className="block text-xs tabular-nums text-gray-500">
                            Projected {pts(m.projected)}, scored {pts(m.actual)}
                          </span>
                        </span>
                        <span
                          className={`shrink-0 tabular-nums font-semibold ${diff > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}`}
                        >
                          {diff > 0 ? "+" : "−"}
                          {pts(Math.abs(diff))}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}

            <details className="mt-10 text-xs leading-5 text-gray-500">
              <summary className="cursor-pointer font-medium text-gray-600 dark:text-gray-300">
                How we grade
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>
                  Projections are saved right before each player&apos;s game, so we grade the
                  last number you saw.
                </li>
                <li>
                  We grade the lineup we recommended before Sunday&apos;s early games, whatever
                  you actually started. Your own lineup is shown next to it.
                </li>
                <li>
                  Players already ruled out (projected 0) aren&apos;t graded.
                </li>
                <li>
                  If a position&apos;s projections have run high or low over the last 6 graded
                  weeks, new ones are nudged the other way: at most 8%, or 1.5 pts for any one
                  player, and less when there are few games to go on.
                </li>
                <li>
                  Only QB, RB, WR and TE count. Our stats source doesn&apos;t include fantasy
                  points for kickers and defenses yet.
                </li>
              </ul>
            </details>
          </>
        )}
      </main>
    </>
  );
}
