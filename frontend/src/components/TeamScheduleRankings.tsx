"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingState, ErrorState } from "@/components/PageState";
import { api } from "@/lib/api";
import { positionColor } from "@/lib/utils";
import {
  cellColor,
  matchupTitle,
  type MatchupCell,
} from "@/lib/schedule";
import PlayerOutlookTable from "@/components/PlayerOutlookTable";

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
  myPlayers: {
    id: string;
    name: string;
    position: string | null;
    team: string | null;
  }[];
}) {
  const [position, setPosition] = useState<string>("RB");
  const [view, setView] = useState<"players" | "teams">("players");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["team-schedule-rankings", leagueId, window],
    queryFn: () =>
      api<TeamRankingsData>(
        `/api/leagues/${leagueId}/schedule-strength/teams?window=${window}`,
      ),
    enabled: view === "teams",
    retry: false,
    staleTime: 30 * 60_000,
  });

  const entries = data?.positions[position] ?? [];
  const mine = (team: string) =>
    myPlayers.filter((p) => p.team === team && p.position === position);

  return (
    <section className="mt-12" aria-labelledby="team-rankings-heading">
      <h2 id="team-rankings-heading" className="text-lg font-semibold">
        {window === "playoffs" ? "Fantasy playoff rankings" : "Rest-of-season rankings"}{" "}
        by position
      </h2>
      <p className="mt-1 text-sm text-gray-500">
        {view === "players"
          ? `Players ranked by projected points over ${
              window === "playoffs" ? "the fantasy playoffs (Wk 15–17)" : "the next six weeks"
            }: how good they are, crossed with who they face. A great player with a tough schedule can slide; a good one with a soft schedule can climb.`
          : `Every NFL team ranked by how soft its ${
              window === "playoffs" ? "fantasy playoff (Wk 15–17)" : "upcoming"
            } schedule is for the position. #1 is the easiest.`}
      </p>

      <div className="mt-4 inline-flex rounded-lg border border-gray-200 p-0.5 dark:border-gray-800">
        {(
          [
            ["players", "Players"],
            ["teams", "Team schedules"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setView(key)}
            aria-pressed={view === key}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              view === key
                ? "bg-ink text-canvas"
                : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

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

      {view === "players" && (
        <PlayerOutlookTable
          leagueId={leagueId}
          window={window}
          position={position}
          myPlayerIds={new Set(myPlayers.map((p) => p.id))}
        />
      )}

      {view === "teams" && isLoading && (
        <LoadingState label="Ranking every team’s schedule…" />
      )}
      {view === "teams" && error ? (
        <ErrorState
          message="We couldn’t load the team rankings. Try again."
          retry={() => void refetch()}
        />
      ) : null}

      {view === "teams" && data && (
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
      {view === "teams" && data && (
        <p className="mt-2 text-xs text-gray-400">
          Based on {data.stats_season} matchup data. Hover a cell for details.
        </p>
      )}
    </section>
  );
}
