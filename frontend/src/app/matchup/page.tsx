"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import PlayerCard from "@/components/PlayerCard";
import { api } from "@/lib/api";
import type { Matchup } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { formatRecord } from "@/lib/utils";

export default function MatchupPage() {
  const { league } = useLeague();

  const { data: matchup, isLoading } = useQuery({
    queryKey: ["matchup", league?.id],
    queryFn: () => api<Matchup>(`/api/leagues/${league!.id}/matchup`),
    enabled: !!league,
    retry: false,
  });

  const teams = [matchup?.user_team, matchup?.opponent_team] as const;

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">
            {matchup?.week ? `Week ${matchup.week} matchup` : "Matchup"}
          </h1>
          <Link
            href={`/chat?q=${encodeURIComponent("Break down my matchup this week")}`}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
          >
            Ask AI to break it down
          </Link>
        </div>

        {isLoading && <p className="mt-4 text-sm text-gray-400">Loading…</p>}
        {!isLoading && !matchup?.opponent_team && (
          <p className="mt-4 text-sm text-gray-400">
            No matchup data yet — schedules appear once your league&apos;s
            season starts. Try Sync after draft day.
          </p>
        )}

        {matchup?.user_team && matchup.opponent_team && (
          <div className="mt-6 grid gap-8 md:grid-cols-2">
            {teams.map((team, idx) =>
              team ? (
                <section
                  key={idx}
                  className={`rounded-xl border p-5 ${
                    idx === 0
                      ? "border-green-300 bg-green-50/40"
                      : "border-gray-200 bg-white"
                  }`}
                >
                  <div className="flex items-baseline justify-between">
                    <h2 className="text-lg font-bold">
                      {idx === 0 ? "You" : team.owner_name ?? "Opponent"}
                    </h2>
                    <span className="text-sm text-gray-500">
                      {formatRecord(team.wins, team.losses, team.ties)} ·{" "}
                      {team.points_for.toFixed(1)} PF
                    </span>
                  </div>
                  <div className="mt-4 space-y-2">
                    {team.starters.map((p, i) => (
                      <PlayerCard key={`${p.id}-${i}`} player={p} />
                    ))}
                  </div>
                </section>
              ) : null
            )}
          </div>
        )}
      </main>
    </>
  );
}
