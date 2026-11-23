"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingState, ErrorState } from "@/components/PageState";
import { api } from "@/lib/api";
import { positionColor } from "@/lib/utils";

export interface MatchupCell {
  week: number;
  opponent: string | null;
  home?: boolean;
  rank: number | null;
  pts_allowed_avg?: number | null;
}

interface TeamEntry {
  team: string;
  rank: number | null;
  avg_value: number | null;
  avg_opp_rank: number | null;
  games: number;
  cells: MatchupCell[];
}

interface TeamRankingsData {
  weeks: number[];
  stats_season: number;
  positions: Record<string, TeamEntry[]>;
}

export const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"] as const;

export function cellColor(rank: number | null): string {
  // Green/gray pick up their dark-mode tints from the global remap layer; the
  // warm tiers need explicit dark variants or they glow cream on the dark theme.
  if (rank == null) return "bg-gray-100 text-gray-400";
  if (rank <= 8) return "bg-green-100 text-green-800";
  if (rank <= 16) return "bg-green-50 text-green-700";
  if (rank <= 24)
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";
}

/** Hover text explaining what a matchup cell's rank means for a position. */
export function matchupTitle(
  position: string | null,
  c: MatchupCell,
): string | undefined {
  if (c.pts_allowed_avg == null || !c.opponent) return undefined;
  if (position === "DEF")
    return `Defenses average ~${c.pts_allowed_avg} fantasy pts vs ${c.opponent}'s offense (rank ${c.rank}/32)`;
  if (position === "K")
    return `${c.opponent} allows ${c.pts_allowed_avg} points/gm (rank ${c.rank}/32 for kickers)`;
  return `${c.opponent} allows ${c.pts_allowed_avg} fantasy pts/gm to ${position}s (rank ${c.rank}/32)`;
}

const VALUE_LABEL: Record<string, string> = {
  DEF: "Avg DST pts",
  K: "Opp pts allowed",
};

export default function TeamScheduleRankings({
  leagueId,
  window,
  myPlayers,
}: {
  leagueId: string;
  window: "upcoming" | "playoffs";
  /** The user's roster, to flag which teams they have a stake in. */
  myPlayers: { name: string; position: string | null; team: string | null }[];
}) {
  const [position, setPosition] = useState<string>("RB");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["team-schedule-rankings", leagueId, window],
    queryFn: () =>
      api<TeamRankingsData>(
        `/api/leagues/${leagueId}/schedule-strength/teams?window=${window}`,
      ),
    retry: false,
    staleTime: 30 * 60_000,
  });

  const entries = data?.positions[position] ?? [];
  const mine = (team: string) =>
    myPlayers.filter((p) => p.team === team && p.position === position);

  return (
    <section className="mt-12" aria-labelledby="team-rankings-heading">
      <h2 id="team-rankings-heading" className="text-lg font-semibold">
        Easiest schedules by position
      </h2>
      <p className="mt-1 text-sm text-gray-500">
        Every NFL team ranked by how soft its{" "}
        {window === "playoffs" ? "fantasy playoff (Wk 15–17)" : "upcoming"}{" "}
        schedule is for the position. #1 is the easiest.
      </p>

      <div
        className="mt-4 flex flex-wrap gap-1.5"
        role="group"
        aria-label="Position"
      >
        {POSITIONS.map((pos) => (
          <button
            key={pos}
            onClick={() => setPosition(pos)}
            aria-pressed={position === pos}
            className={`rounded-full px-3 py-1 text-sm font-medium ${
              position === pos
                ? "bg-ink text-canvas"
                : "border border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
            }`}
          >
            {pos}
          </button>
        ))}
      </div>

      {isLoading && <LoadingState label="Ranking every team’s schedule…" />}
      {error ? (
        <ErrorState
          message="We couldn’t load the team rankings. Try again."
          retry={() => void refetch()}
        />
      ) : null}

      {data && (
        <div className="mt-4 overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs font-medium text-gray-500">
                <th className="px-4 py-3">#</th>
                <th className="px-2 py-3">Team</th>
                <th
                  className="px-2 py-3 text-right"
                  title={
                    position === "DEF"
                      ? "Fantasy points a league-average defense is expected to score against these offenses"
                      : position === "K"
                        ? "Points per game these defenses allow"
                        : `Fantasy points per game these defenses allow to ${position}s`
                  }
                >
                  {VALUE_LABEL[position] ?? "Avg pts allowed"}
                </th>
                {data.weeks.map((w) => (
                  <th key={w} className="px-2 py-3 text-center">
                    W{w}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => {
                const yours = mine(e.team);
                return (
                  <tr
                    key={e.team}
                    className={`border-b border-gray-50 last:border-0 ${
                      yours.length ? "bg-accent-soft" : ""
                    }`}
                  >
                    <td className="px-4 py-2 font-semibold tabular-nums">
                      {e.rank ?? "–"}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <span className="w-9 font-medium">{e.team}</span>
                        {yours.length > 0 && (
                          <span
                            className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${positionColor(position)}`}
                            title={yours.map((p) => p.name).join(", ")}
                          >
                            Yours: {yours.map((p) => p.name).join(", ")}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums text-gray-600">
                      {e.avg_value ?? "–"}
                    </td>
                    {e.cells.map((c) => (
                      <td key={c.week} className="px-1 py-1.5 text-center">
                        {c.opponent ? (
                          <span
                            title={matchupTitle(position, c)}
                            className={`block rounded px-1.5 py-1.5 text-xs font-medium ${cellColor(c.rank)}`}
                          >
                            {c.home ? "" : "@"}
                            {c.opponent}
                          </span>
                        ) : (
                          <span className="block rounded bg-gray-50 px-1.5 py-1.5 text-xs text-gray-300">
                            BYE
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <p className="mt-2 text-xs text-gray-400">
          Based on {data.stats_season} matchup data. Hover a cell for details.
        </p>
      )}
    </section>
  );
}
