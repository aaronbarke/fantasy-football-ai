"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import InjuryBadge from "@/components/InjuryBadge";
import { api } from "@/lib/api";
import type { Matchup, Roster, StandingsEntry } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { formatRecord } from "@/lib/utils";
import { MessageCircle, RefreshCw } from "lucide-react";
import { useState } from "react";

const quickAsks = [
  "Who should I start this week?",
  "Who should I pick up off waivers?",
  "Break down my matchup this week",
];

export default function DashboardPage() {
  const router = useRouter();
  const { league, leagues, selectLeague } = useLeague();
  const [syncing, setSyncing] = useState(false);

  const { data: roster } = useQuery({
    queryKey: ["roster", league?.id],
    queryFn: () => api<Roster>(`/api/leagues/${league!.id}/roster`),
    enabled: !!league,
    retry: false,
  });

  const { data: matchup } = useQuery({
    queryKey: ["matchup", league?.id],
    queryFn: () => api<Matchup>(`/api/leagues/${league!.id}/matchup`),
    enabled: !!league,
    retry: false,
  });

  const { data: standings } = useQuery({
    queryKey: ["standings", league?.id],
    queryFn: () => api<StandingsEntry[]>(`/api/leagues/${league!.id}/standings`),
    enabled: !!league,
  });

  const { data: recSummary } = useQuery({
    queryKey: ["rec-summary", league?.id],
    queryFn: () =>
      api<{ wins: number; losses: number; ties: number; pending: number }>(
        `/api/recommendations/summary?connection_id=${league!.id}`
      ),
    enabled: !!league,
  });

  const injured =
    roster &&
    [...roster.starters, ...roster.bench].filter((p) => p.injury_status);

  const rank =
    standings && roster
      ? standings.findIndex((s) => s.team_id === roster.team_id) + 1
      : null;

  async function claimTeam(teamId: string) {
    if (!league || !teamId) return;
    await api(`/api/leagues/${league.id}/claim-team`, {
      method: "POST",
      body: JSON.stringify({ team_id: teamId }),
    });
    window.location.reload();
  }

  async function syncNow() {
    if (!league) return;
    setSyncing(true);
    try {
      await api(`/api/leagues/${league.id}/sync`, { method: "POST" });
      window.location.reload();
    } finally {
      setSyncing(false);
    }
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">
              {league?.league_name ?? "Dashboard"}
            </h1>
            <p className="text-sm text-gray-500">
              {league
                ? `${league.platform} · ${league.season} · ${league.scoring_type?.replace("_", "-").toUpperCase() ?? ""}`
                : "Loading league…"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {leagues.length > 1 && (
              <select
                value={league?.id}
                onChange={(e) => selectLeague(e.target.value)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm"
              >
                {leagues.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.league_name ?? l.league_id}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={syncNow}
              disabled={syncing}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100 disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
              Sync
            </button>
          </div>
        </div>

        {league && !league.team_id && standings && standings.length > 0 && (
          <div className="mt-6 rounded-xl border border-yellow-200 bg-yellow-50 px-6 py-4">
            <p className="text-sm font-semibold text-yellow-800">
              Which team is yours? We couldn&apos;t detect it automatically.
            </p>
            <select
              defaultValue=""
              onChange={(e) => claimTeam(e.target.value)}
              className="mt-2 rounded-lg border border-yellow-300 bg-white px-3 py-1.5 text-sm"
            >
              <option value="" disabled>
                Select your team…
              </option>
              {standings.map((s) => (
                <option key={s.team_id} value={s.team_id}>
                  {s.owner_name ?? `Team ${s.team_id}`}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          {/* Record card */}
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-gray-500">Your team</h2>
            {roster ? (
              <>
                <p className="mt-2 text-3xl font-bold">
                  {formatRecord(roster.wins, roster.losses, roster.ties)}
                </p>
                <p className="mt-1 text-sm text-gray-500">
                  {rank ? `#${rank} in standings · ` : ""}
                  {roster.points_for.toFixed(1)} PF /{" "}
                  {roster.points_against.toFixed(1)} PA
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-gray-400">
                No roster yet — try syncing.
              </p>
            )}
          </div>

          {/* Matchup card */}
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-gray-500">
              {matchup?.week ? `Week ${matchup.week} matchup` : "Matchup"}
            </h2>
            {matchup?.opponent_team ? (
              <>
                <p className="mt-2 text-lg font-bold">
                  vs {matchup.opponent_team.owner_name ?? "Opponent"}
                </p>
                <p className="mt-1 text-sm text-gray-500">
                  They&apos;re{" "}
                  {formatRecord(
                    matchup.opponent_team.wins,
                    matchup.opponent_team.losses,
                    matchup.opponent_team.ties
                  )}{" "}
                  with {matchup.opponent_team.points_for.toFixed(1)} PF
                </p>
                <Link
                  href="/matchup"
                  className="mt-3 inline-block text-sm font-medium text-green-700 hover:underline"
                >
                  Full breakdown →
                </Link>
              </>
            ) : (
              <p className="mt-2 text-sm text-gray-400">No matchup data yet.</p>
            )}
          </div>

          {/* Injury alerts */}
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="text-sm font-semibold text-gray-500">Injury alerts</h2>
            {injured && injured.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {injured.slice(0, 5).map((p) => (
                  <li key={p.id} className="flex items-center justify-between">
                    <span className="text-sm font-medium">{p.name}</span>
                    <InjuryBadge status={p.injury_status} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-gray-400">
                No injuries on your roster. 🎉
              </p>
            )}
          </div>
        </div>

        {/* AI accuracy */}
        {recSummary && recSummary.wins + recSummary.losses + recSummary.pending > 0 && (
          <div className="mt-6 rounded-xl border border-green-200 bg-green-50 px-6 py-4">
            <p className="text-sm font-semibold text-green-800">
              AI start/sit record: {recSummary.wins}-{recSummary.losses}
              {recSummary.ties > 0 ? `-${recSummary.ties}` : ""}
              {recSummary.pending > 0 && (
                <span className="ml-2 font-normal text-green-700">
                  ({recSummary.pending} call{recSummary.pending === 1 ? "" : "s"} pending
                  this week&apos;s results)
                </span>
              )}
            </p>
          </div>
        )}

        {/* Game plan promo */}
        <Link
          href="/gameplan"
          className="mt-6 flex items-center justify-between rounded-xl border border-green-300 bg-gradient-to-r from-green-600 to-green-700 px-6 py-5 text-white shadow-md transition-transform hover:scale-[1.01]"
        >
          <div>
            <p className="text-lg font-bold">This week&apos;s game plan →</p>
            <p className="mt-0.5 text-sm text-green-100">
              Optimal lineup, projected score, and win odds — built by the model.
            </p>
          </div>
          <span className="hidden rounded-full bg-white/15 px-3 py-1 text-xs font-semibold sm:block">
            NEW
          </span>
        </Link>

        {/* Quick asks */}
        <div className="mt-8">
          <h2 className="text-sm font-semibold text-gray-500">Ask the AI</h2>
          <div className="mt-3 flex flex-wrap gap-3">
            {quickAsks.map((q) => (
              <button
                key={q}
                onClick={() => router.push(`/chat?q=${encodeURIComponent(q)}`)}
                className="flex items-center gap-2 rounded-full border border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-800 hover:bg-green-100"
              >
                <MessageCircle className="h-4 w-4" />
                {q}
              </button>
            ))}
          </div>
        </div>

        {/* Standings */}
        {standings && standings.length > 0 && (
          <div className="mt-8 rounded-xl border border-gray-200 bg-white">
            <h2 className="border-b border-gray-100 px-6 py-4 text-sm font-semibold text-gray-500">
              Standings
            </h2>
            <table className="w-full text-sm">
              <tbody>
                {standings.map((s, i) => (
                  <tr
                    key={s.team_id}
                    className={`border-b border-gray-50 last:border-0 ${
                      s.team_id === roster?.team_id ? "bg-green-50" : ""
                    }`}
                  >
                    <td className="px-6 py-2.5 text-gray-400">{i + 1}</td>
                    <td className="py-2.5 font-medium">
                      {s.owner_name ?? `Team ${s.team_id}`}
                    </td>
                    <td className="py-2.5">{formatRecord(s.wins, s.losses, s.ties)}</td>
                    <td className="px-6 py-2.5 text-right text-gray-500">
                      {s.points_for.toFixed(1)} PF
                    </td>
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
