"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
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

function record(w: number, l: number, t: number): string {
  return t ? `${w}–${l}–${t}` : `${w}–${l}`;
}

/** "we run 0.8 high" / "0.8 low" — bias is actual minus projected. */
function biasText(bias: number): string {
  if (Math.abs(bias) < 0.1) return "no lean high or low";
  return bias > 0
    ? `players beat us by ${bias.toFixed(1)} on average`
    : `we run ${Math.abs(bias).toFixed(1)} high on average`;
}

function changesText(w: LineupWeek): string {
  if (w.your_changes == null) return "—";
  if (w.your_changes.length === 0) return "Played our lineup";
  return w.your_changes
    .map((c) =>
      c.started
        ? `${c.started} (${c.started_points}) over our ${c.instead_of ?? "—"}` +
          (c.instead_points != null ? ` (${c.instead_points})` : "")
        : `left our ${c.instead_of} (${c.instead_points}) out`,
    )
    .join("; ");
}

function signed(n: number): string {
  if (Math.abs(n) < 0.05) return "0.0";
  return `${n > 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
}

function Tile({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      {detail && <p className="mt-1 text-xs text-gray-500">{detail}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

const tableClass =
  "w-full overflow-hidden rounded-xl border border-gray-200 bg-white text-sm dark:border-gray-800";
const thClass = "px-3 py-2 text-left text-xs font-medium text-gray-500";
const tdClass = "border-t border-gray-100 px-3 py-2 tabular-nums dark:border-gray-800";

export default function AccuracyPage() {
  const { league } = useLeague();
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
  const nothingTracked = data && data.weeks_tracked.length === 0;
  const waiting = data && !nothingTracked && !overall && !lineups;

  return (
    <>
      <Navbar />
      <main id="main-content" tabIndex={-1} className="mx-auto max-w-5xl px-4 py-8">
        <PageHeader
          eyebrow="How our calls held up"
          title="Track record"
          description="Before each kickoff we save every projection and the lineup we recommend, then grade them once the week's stats are in."
        />

        {isLoading && <LoadingState label="Grading our calls…" />}
        {error && <ErrorState retry={() => void refetch()} />}

        {nothingTracked && (
          <EmptyState
            title="Tracking starts this week"
            description="We save projections and your recommended lineup before each game, then grade them after the games — usually by Tuesday morning."
          />
        )}
        {waiting && (
          <EmptyState
            title={`Week ${data!.pending_weeks.join(", ")} is being tracked`}
            description="Grades post once the week's games are final and the stats are in — usually Tuesday morning."
          />
        )}

        {data && (overall || lineups) && (
          <>
            {data.pending_weeks.length > 0 && (
              <p className="mt-4 text-xs text-gray-500">
                Week {data.pending_weeks.join(", ")} is still being tracked and will be
                graded once it&apos;s final.
              </p>
            )}

            <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Tile
                label="Start/sit calls"
                value={gp ? record(gp.wins, gp.losses, gp.ties) : "—"}
                detail={
                  chat && chat.wins + chat.losses + chat.ties > 0
                    ? `Chat picks ${record(chat.wins, chat.losses, chat.ties)}`
                    : "Game plan swaps"
                }
              />
              <Tile
                label="Lineup accuracy"
                value={lineups ? `${lineups.correct} of ${lineups.slots}` : "—"}
                detail={
                  lineups
                    ? `${lineups.perfect_weeks} perfect week${lineups.perfect_weeks === 1 ? "" : "s"} · ${lineups.avg_points_left} pts/wk left on the bench`
                    : "Starters we got right"
                }
              />
              <Tile
                label="Average projection miss"
                value={overall ? `±${overall.avg_miss.toFixed(1)}` : "—"}
                detail={overall ? biasText(overall.bias) : undefined}
              />
              <Tile
                label="Us vs Sleeper alone"
                value={
                  vs?.ours != null && vs.sleeper_only != null
                    ? `${vs.ours.toFixed(1)} vs ${vs.sleeper_only.toFixed(1)}`
                    : "—"
                }
                detail={
                  vs?.ours != null && vs.sleeper_only != null
                    ? vs.ours <= vs.sleeper_only
                      ? `Our blend misses ${(vs.sleeper_only - vs.ours).toFixed(1)} pts less`
                      : `Sleeper alone misses ${(vs.ours - vs.sleeper_only).toFixed(1)} pts less`
                    : "Average miss, same players"
                }
              />
            </div>

            {data.lineups.weeks.length > 0 && (
              <Section title="Lineups, week by week">
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <thead>
                      <tr>
                        <th className={thClass}>Week</th>
                        <th className={thClass}>Starters right</th>
                        <th className={thClass}>Our lineup</th>
                        <th className={thClass}>Best possible</th>
                        <th className={thClass}>Your lineup</th>
                        <th className={thClass}>We should have started</th>
                        <th className={thClass}>Your changes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.lineups.weeks.map((w) => (
                        <tr key={w.week}>
                          <td className={tdClass}>{w.week}</td>
                          <td className={tdClass}>
                            {w.correct}/{w.slots}
                          </td>
                          <td className={tdClass}>{w.recommended_points.toFixed(1)}</td>
                          <td className={tdClass}>{w.best_points.toFixed(1)}</td>
                          <td className={tdClass}>
                            {w.your_points != null ? w.your_points.toFixed(1) : "—"}
                          </td>
                          <td className={`${tdClass} text-xs text-gray-600 dark:text-gray-300`}>
                            {w.should_have_started.length
                              ? `${w.should_have_started.join(", ")} over ${w.should_have_sat.join(", ")}`
                              : "Nothing — perfect lineup"}
                          </td>
                          <td className={`${tdClass} text-xs text-gray-600 dark:text-gray-300`}>
                            {changesText(w)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {lineups && lineups.weeks_with_your_lineup > 0 && (
                  <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
                    You played our lineup in {lineups.weeks_followed} of{" "}
                    {lineups.weeks_with_your_lineup} week
                    {lineups.weeks_with_your_lineup === 1 ? "" : "s"}
                    {lineups.avg_your_changes_net != null &&
                      lineups.weeks_followed < lineups.weeks_with_your_lineup &&
                      `; your changes ${
                        lineups.avg_your_changes_net >= 0 ? "gained" : "cost"
                      } ${Math.abs(lineups.avg_your_changes_net).toFixed(1)} pts a week on average`}
                    .
                  </p>
                )}
                <p className="mt-2 text-xs text-gray-500">
                  We grade the lineup we projected highest, saved before kickoff — whatever
                  you actually start. Your lineup is shown alongside, as you played it.
                  QB/RB/WR/TE slots only.
                </p>
              </Section>
            )}

            {gp && gp.calls.length > 0 && (
              <Section title="Start/sit calls">
                <ul className="space-y-1.5">
                  {gp.calls.map((c, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-800"
                    >
                      <span className="min-w-0 truncate">
                        <span className="text-gray-400">Wk {c.week} · </span>
                        Start <strong>{c.start}</strong> ({c.start_points}) over{" "}
                        <strong>{c.sit}</strong> ({c.sit_points})
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${
                          c.result === "win"
                            ? "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300"
                            : c.result === "loss"
                              ? "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300"
                              : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
                        }`}
                      >
                        {c.result === "win" ? "Right" : c.result === "loss" ? "Wrong" : "Tie"}
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            {overall && (
              <Section title="Projections vs actual points">
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <thead>
                      <tr>
                        <th className={thClass}>Position</th>
                        <th className={thClass}>Players graded</th>
                        <th className={thClass}>Average miss</th>
                        <th className={thClass}>Lean</th>
                        <th className={thClass}>Inside floor–ceiling</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(["QB", "RB", "WR", "TE"] as const).map((pos) => {
                        const s = data.projections.by_position[pos];
                        if (!s) return null;
                        return (
                          <tr key={pos}>
                            <td className={tdClass}>
                              <span
                                className={`inline-flex h-6 w-8 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(pos)}`}
                              >
                                {pos}
                              </span>
                            </td>
                            <td className={tdClass}>{s.count}</td>
                            <td className={tdClass}>±{s.avg_miss.toFixed(1)}</td>
                            <td className={tdClass}>{signed(s.bias)}</td>
                            <td className={tdClass}>
                              {s.within_range_pct != null ? `${s.within_range_pct}%` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-gray-500">
                  Lean is actual minus projected: + means players beat our number. Every
                  tracked player counts here, not just your roster. Players already ruled
                  out (projected 0) aren&apos;t graded.
                </p>
              </Section>
            )}

            {data.projections.your_players.length > 0 && (
              <Section title="Your players">
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <thead>
                      <tr>
                        <th className={thClass}>Player</th>
                        <th className={thClass}>Games</th>
                        <th className={thClass}>Avg projected</th>
                        <th className={thClass}>Avg actual</th>
                        <th className={thClass}>Average miss</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.projections.your_players.map((p) => (
                        <tr key={p.id}>
                          <td className={`${tdClass} font-medium`}>
                            {p.name}
                            <span className="ml-1.5 text-xs text-gray-400">{p.position}</span>
                          </td>
                          <td className={tdClass}>{p.games}</td>
                          <td className={tdClass}>{p.avg_projected.toFixed(1)}</td>
                          <td className={tdClass}>{p.avg_actual.toFixed(1)}</td>
                          <td className={tdClass}>±{p.avg_miss.toFixed(1)}</td>
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
                  {data.projections.biggest_misses.map((m, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-800"
                    >
                      <span className="min-w-0 truncate">
                        <span className="text-gray-400">Wk {m.week} · </span>
                        {m.name}
                      </span>
                      <span className="shrink-0 tabular-nums text-gray-600 dark:text-gray-300">
                        proj {m.projected} → {m.actual}
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            )}

            <p className="mt-8 text-xs text-gray-500">
              Kickers and defenses aren&apos;t graded yet — the stats feed we grade against
              doesn&apos;t carry their fantasy points.
            </p>
          </>
        )}
      </main>
    </>
  );
}
