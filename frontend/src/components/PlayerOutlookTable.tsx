"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LoadingState, ErrorState } from "@/components/PageState";
import { api } from "@/lib/api";
import { positionColor } from "@/lib/utils";
import { cellColor, type MatchupCell } from "@/lib/schedule";

interface OutlookCell extends MatchupCell {
  proj: number;
}

interface OutlookEntry {
  id: string;
  name: string;
  team: string | null;
  injury_status: string | null;
  base_ppg: number;
  base_rank: number;
  proj_ppg: number;
  proj_total: number;
  rank: number;
  games: number;
  vs_tough_ppg?: number | null;
  vs_tough_games?: number;
  cells: OutlookCell[];
}

interface OutlookData {
  weeks: number[];
  stats_season: number;
  positions: Record<string, OutlookEntry[]>;
}

function Move({ from, to }: { from: number; to: number }) {
  const d = from - to;
  if (d === 0) return <span className="text-gray-300">–</span>;
  return (
    <span
      className={
        d > 0
          ? "text-green-700 dark:text-green-400"
          : "text-red-700 dark:text-red-400"
      }
      title={`${d > 0 ? "Up" : "Down"} ${Math.abs(d)} from his #${from} scoring rank`}
    >
      {d > 0 ? "▲" : "▼"}
      {Math.abs(d)}
    </span>
  );
}

const INITIAL_ROWS = 50;

/** Players at one position ranked by projected points over the window:
 *  how good they are, crossed with who they face. */
export default function PlayerOutlookTable({
  leagueId,
  window,
  position,
  myPlayerIds,
}: {
  leagueId: string;
  window: "upcoming" | "playoffs";
  position: string;
  myPlayerIds: Set<string>;
}) {
  const [showAll, setShowAll] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["player-schedule-outlook", leagueId, window],
    queryFn: () =>
      api<OutlookData>(
        `/api/leagues/${leagueId}/schedule-strength/players?window=${window}`,
      ),
    retry: false,
    staleTime: 30 * 60_000,
  });

  if (isLoading) return <LoadingState label="Projecting every player’s run…" />;
  if (error)
    return (
      <ErrorState
        message="We couldn’t load the player outlook. Try again."
        retry={() => void refetch()}
      />
    );
  if (!data) return null;

  const all = data.positions[position] ?? [];
  const entries = showAll ? all : all.slice(0, INITIAL_ROWS);
  const teamPos = position === "K" || position === "DEF";

  return (
    <>
      <div className="mt-4 overflow-x-auto rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs font-medium text-gray-500">
              <th className="px-4 py-3">#</th>
              <th className="px-2 py-3">Player</th>
              <th
                className="px-2 py-3 text-right"
                title={
                  teamPos
                    ? "Projected points per game against a league-average opponent"
                    : "Recent-weighted fantasy points per game, and where that ranks at the position"
                }
              >
                {teamPos ? "Neutral pts/gm" : "Pts/gm"}
              </th>
              {!teamPos && (
                <th
                  className="px-2 py-3 text-right"
                  title="His fantasy points per game this season against the toughest third of defenses for his position"
                >
                  vs tough D
                </th>
              )}
              <th
                className="px-2 py-3 text-center"
                title="Spots gained or lost once the schedule is applied"
              >
                Sched.
              </th>
              <th
                className="px-2 py-3 text-right"
                title="Projected points per game over these weeks"
              >
                Proj/gm
              </th>
              {data.weeks.map((w) => (
                <th key={w} className="px-2 py-3 text-center">
                  W{w}
                </th>
              ))}
              <th className="px-3 py-3 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr
                key={e.id}
                className={`border-b border-gray-50 last:border-0 ${
                  myPlayerIds.has(e.id) ? "bg-accent-soft" : ""
                }`}
              >
                <td className="px-4 py-2 font-semibold tabular-nums">
                  {e.rank}
                </td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <span className="whitespace-nowrap font-medium">
                      {e.name}
                    </span>
                    <span className="text-xs text-gray-400">{e.team}</span>
                    {e.injury_status && (
                      <span className="rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                        {e.injury_status}
                      </span>
                    )}
                    {myPlayerIds.has(e.id) && (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-semibold text-white ${positionColor(position)}`}
                      >
                        Yours
                      </span>
                    )}
                  </div>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums text-gray-600">
                  {e.base_ppg}{" "}
                  <span className="text-xs text-gray-400">#{e.base_rank}</span>
                </td>
                {!teamPos && (
                  <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums text-gray-600">
                    {e.vs_tough_ppg ?? "–"}{" "}
                    {e.vs_tough_games ? (
                      <span className="text-xs text-gray-400">
                        ({e.vs_tough_games}g)
                      </span>
                    ) : null}
                  </td>
                )}
                <td className="px-2 py-2 text-center text-xs font-semibold tabular-nums">
                  <Move from={e.base_rank} to={e.rank} />
                </td>
                <td className="px-2 py-2 text-right font-medium tabular-nums">
                  {e.proj_ppg}
                </td>
                {e.cells.map((c) => (
                  <td key={c.week} className="px-1 py-1.5 text-center">
                    {c.opponent ? (
                      <span
                        title={`Projected ${c.proj} pts vs ${c.opponent}${
                          c.rank != null ? ` (matchup rank ${c.rank}/32; 1 = easiest)` : ""
                        }`}
                        className={`block rounded px-1.5 py-1 text-xs font-medium leading-tight ${cellColor(c.rank)}`}
                      >
                        {c.home ? "" : "@"}
                        {c.opponent}
                        <span className="block text-[10px] font-normal opacity-80">
                          {c.proj}
                        </span>
                      </span>
                    ) : (
                      <span className="block rounded bg-gray-50 px-1.5 py-1.5 text-xs text-gray-300">
                        BYE
                      </span>
                    )}
                  </td>
                ))}
                <td className="px-3 py-2 text-right font-semibold tabular-nums">
                  {e.proj_total}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {all.length > INITIAL_ROWS && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 rounded-lg border border-gray-200 px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          {showAll ? `Show top ${INITIAL_ROWS}` : `Show all ${all.length} ${position}s`}
        </button>
      )}
      <p className="mt-2 text-xs text-gray-400">
        {teamPos
          ? "Kickers follow their offense’s scoring and the opponent’s points allowed; defenses follow their own quality and the opposing offense."
          : "Each game is 75% the player — his points per game (last 4 games count double; last season fades out after 8 games), or his own record against defenses that tough or soft — and 25% the matchup: how many points that defense allows to the position."}{" "}
        Players on IR or PUP are left out. Based on {data.stats_season} data.
      </p>
    </>
  );
}
