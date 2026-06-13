"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";

interface Cell {
  week: number;
  opponent: string | null;
  home?: boolean;
  rank: number | null;
  pts_allowed_avg?: number | null;
}

interface StrengthPlayer {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  cells: Cell[];
}

interface StrengthData {
  weeks: number[];
  stats_season: number;
  players: StrengthPlayer[];
}

function cellColor(rank: number | null): string {
  // Green/gray pick up their dark-mode tints from the global remap layer; the
  // warm tiers need explicit dark variants or they glow cream on the dark theme.
  if (rank == null) return "bg-gray-100 text-gray-400";
  if (rank <= 8) return "bg-green-100 text-green-800";
  if (rank <= 16) return "bg-green-50 text-green-700";
  if (rank <= 24) return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";
}

export default function SchedulePage() {
  const { league } = useLeague();
  const router = useRouter();

  const { data, isLoading, error } = useQuery({
    queryKey: ["schedule-strength", league?.id],
    queryFn: () => api<StrengthData>(`/api/leagues/${league!.id}/schedule-strength`),
    enabled: !!league,
    retry: false,
    staleTime: 30 * 60_000,
  });

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-bold">Schedule strength</h1>
        <p className="mt-1 text-sm text-gray-500">
          Upcoming matchup difficulty for your roster. Green = the opponent
          allows a lot of fantasy points to that position; red = tough matchup.
          {data ? ` Based on ${data.stats_season} defensive stats.` : ""}
        </p>

        {isLoading && <p className="mt-6 text-sm text-gray-400">Crunching the schedule…</p>}
        {error ? (
          <p className="mt-6 text-sm text-gray-400">
            No data yet — this fills in once your roster has players (after
            your draft, hit Sync on the dashboard).
          </p>
        ) : null}
        {data && data.players.length === 0 && (
          <p className="mt-6 text-sm text-gray-400">
            Your roster is empty — the heatmap appears after draft day.
          </p>
        )}

        {data && (
          <div className="mt-6 overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                  <th className="px-4 py-3">Player</th>
                  {data.weeks.map((w) => (
                    <th key={w} className="px-2 py-3 text-center">
                      W{w}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.players.map((p) => (
                  <tr key={p.id} className="border-b border-gray-50 last:border-0">
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                        >
                          {p.position}
                        </span>
                        <span className="whitespace-nowrap font-medium">{p.name}</span>
                        <span className="text-xs text-gray-400">{p.team}</span>
                      </div>
                    </td>
                    {p.cells.map((c) => (
                      <td key={c.week} className="px-1 py-1.5 text-center">
                        {c.opponent ? (
                          <button
                            onClick={() =>
                              router.push(
                                `/chat?q=${encodeURIComponent(
                                  `How does ${p.name}'s week ${c.week} matchup against ${c.opponent} look?`
                                )}`
                              )
                            }
                            title={
                              c.pts_allowed_avg != null
                                ? `${c.opponent} allows ${c.pts_allowed_avg} PPR/gm to ${p.position}s (rank ${c.rank}/32)`
                                : undefined
                            }
                            className={`w-full rounded px-1.5 py-1.5 text-xs font-medium hover:ring-2 hover:ring-green-400 ${cellColor(c.rank)}`}
                          >
                            {c.home ? "" : "@"}
                            {c.opponent}
                          </button>
                        ) : (
                          <span className="block rounded bg-gray-50 px-1.5 py-1.5 text-xs text-gray-300">
                            BYE
                          </span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </>
  );
}
