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
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  Crown,
  MessageCircle,
  RefreshCw,
  Shield,
  Swords,
  Target,
  Trophy,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useState } from "react";

const quickAsks = [
  { q: "Who should I start this week?", icon: Target },
  { q: "Who should I pick up off waivers?", icon: TrendingUp },
  { q: "Break down my matchup this week", icon: Swords },
];

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center rounded-lg bg-white/60 px-4 py-2.5 dark:bg-white/5">
      <span className="text-lg font-bold text-gray-900 dark:text-gray-100">{value}</span>
      <span className="text-[11px] font-medium uppercase tracking-wider text-gray-400">{label}</span>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { league, leagues, selectLeague } = useLeague();
  const [syncing, setSyncing] = useState(false);

  const { data: roster, isLoading: rosterLoading } = useQuery({
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

  const totalTeams = standings?.length ?? 0;

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
      <main className="mx-auto max-w-6xl px-4 py-6">
        {/* ── Hero header ── */}
        <div className="relative overflow-hidden rounded-2xl border border-gray-200/60 bg-gradient-to-br from-green-600 via-green-700 to-emerald-800 p-6 shadow-lg dark:border-green-900/40 dark:from-green-900 dark:via-green-950 dark:to-gray-950 sm:p-8">
          <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-white/5" />
          <div className="pointer-events-none absolute -bottom-20 -left-20 h-72 w-72 rounded-full bg-white/[0.03]" />

          <div className="relative flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-green-200" />
                <span className="text-xs font-semibold uppercase tracking-widest text-green-200">
                  {league?.platform} &middot; {league?.season}
                </span>
              </div>
              <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
                {league?.league_name ?? "Dashboard"}
              </h1>
              {roster && (
                <p className="mt-1 text-sm text-green-100/80">
                  {roster.owner_name ?? "Your team"}
                  {rank ? ` · #${rank} of ${totalTeams}` : ""}
                </p>
              )}
            </div>

            {roster && (
              <div className="flex gap-3">
                <StatPill label="Record" value={formatRecord(roster.wins, roster.losses, roster.ties)} />
                <StatPill label="PF" value={roster.points_for.toFixed(1)} />
                <StatPill label="PA" value={roster.points_against.toFixed(1)} />
              </div>
            )}

            {rosterLoading && (
              <div className="flex gap-3">
                <div className="skeleton h-14 w-20 rounded-lg !bg-white/10" />
                <div className="skeleton h-14 w-20 rounded-lg !bg-white/10" />
                <div className="skeleton h-14 w-20 rounded-lg !bg-white/10" />
              </div>
            )}
          </div>

          {/* Sync + league switcher */}
          <div className="relative mt-5 flex items-center gap-2 border-t border-white/10 pt-4">
            {leagues.length > 1 && (
              <select
                value={league?.id}
                onChange={(e) => selectLeague(e.target.value)}
                className="rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm"
              >
                {leagues.map((l) => (
                  <option key={l.id} value={l.id} className="text-gray-900">
                    {l.league_name ?? l.league_id}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={syncNow}
              disabled={syncing}
              className="flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 text-xs font-medium text-white backdrop-blur-sm hover:bg-white/20 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              Sync now
            </button>
          </div>
        </div>

        {/* Team claim banner */}
        {league && !league.team_id && standings && standings.length > 0 && (
          <div className="mt-4 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-3 dark:border-amber-800/50 dark:bg-amber-950/30">
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                Which team is yours?
              </p>
              <p className="text-xs text-amber-600 dark:text-amber-400">
                We couldn&apos;t detect it automatically.
              </p>
            </div>
            <select
              defaultValue=""
              onChange={(e) => claimTeam(e.target.value)}
              className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm dark:border-amber-700 dark:bg-gray-900"
            >
              <option value="" disabled>Select your team…</option>
              {standings.map((s) => (
                <option key={s.team_id} value={s.team_id}>
                  {s.owner_name ?? `Team ${s.team_id}`}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* ── Game plan CTA ── */}
        <Link
          href="/gameplan"
          className="group mt-6 flex items-center gap-4 rounded-2xl border border-green-200/60 bg-gradient-to-r from-green-50 to-emerald-50 p-5 shadow-sm transition-all hover:shadow-md hover:border-green-300 dark:border-green-800/40 dark:from-green-950/50 dark:to-emerald-950/30 dark:hover:border-green-700/60"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-green-600 text-white shadow-md shadow-green-600/25">
            <Zap className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <p className="text-base font-bold text-gray-900 dark:text-gray-100">
              Weekly Game Plan
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Optimal lineup, projected score, and win odds — built by the model.
            </p>
          </div>
          <div className="flex items-center gap-1.5 rounded-full bg-green-600 px-3 py-1 text-xs font-bold text-white shadow-sm transition-transform group-hover:translate-x-0.5">
            GO <ArrowRight className="h-3.5 w-3.5" />
          </div>
        </Link>

        {/* ── Two-column: Matchup + Injuries ── */}
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {/* Matchup */}
          <div className="rounded-2xl border border-gray-200/60 bg-white p-6 dark:border-gray-800/60">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
              <Swords className="h-3.5 w-3.5" />
              {matchup?.week ? `Week ${matchup.week} matchup` : "This week"}
            </div>
            {matchup?.opponent_team ? (
              <div className="mt-4">
                <div className="flex items-center justify-between">
                  <div className="text-center">
                    <p className="text-xs font-medium text-gray-400">YOU</p>
                    <p className="mt-1 text-2xl font-extrabold text-gray-900 dark:text-gray-100">
                      {formatRecord(roster?.wins ?? 0, roster?.losses ?? 0, roster?.ties ?? 0)}
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500">{roster?.points_for.toFixed(1)} PF</p>
                  </div>
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
                    <span className="text-xs font-bold text-gray-400">VS</span>
                  </div>
                  <div className="text-center">
                    <p className="text-xs font-medium text-gray-400">OPP</p>
                    <p className="mt-1 text-2xl font-extrabold text-gray-900 dark:text-gray-100">
                      {formatRecord(
                        matchup.opponent_team.wins,
                        matchup.opponent_team.losses,
                        matchup.opponent_team.ties
                      )}
                    </p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {matchup.opponent_team.points_for.toFixed(1)} PF
                    </p>
                  </div>
                </div>
                <p className="mt-3 text-center text-sm font-medium text-gray-600 dark:text-gray-300">
                  vs {matchup.opponent_team.owner_name ?? "Opponent"}
                </p>
                <Link
                  href="/matchup"
                  className="mt-4 flex items-center justify-center gap-1 rounded-lg bg-gray-100 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Full breakdown <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
            ) : (
              <div className="mt-6 flex flex-col items-center py-4 text-gray-400">
                <Swords className="h-8 w-8 stroke-1" />
                <p className="mt-2 text-sm">No matchup data yet.</p>
              </div>
            )}
          </div>

          {/* Injury alerts */}
          <div className="rounded-2xl border border-gray-200/60 bg-white p-6 dark:border-gray-800/60">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
              <Activity className="h-3.5 w-3.5" />
              Injury report
            </div>
            {injured && injured.length > 0 ? (
              <ul className="mt-4 space-y-3">
                {injured.slice(0, 6).map((p) => (
                  <li key={p.id} className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-100 text-[10px] font-bold text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                      {p.position}
                    </div>
                    <div className="flex-1">
                      <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{p.name}</p>
                      <p className="text-xs text-gray-400">{p.team}</p>
                    </div>
                    <InjuryBadge status={p.injury_status} />
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-6 flex flex-col items-center py-4 text-gray-400">
                <Activity className="h-8 w-8 stroke-1" />
                <p className="mt-2 text-sm">All clear — no injuries on your roster.</p>
              </div>
            )}
          </div>
        </div>

        {/* ── AI record ── */}
        {recSummary && recSummary.wins + recSummary.losses + recSummary.pending > 0 && (
          <div className="mt-6 flex items-center gap-4 rounded-2xl border border-green-200/60 bg-gradient-to-r from-green-50 to-emerald-50/50 px-6 py-4 dark:border-green-800/40 dark:from-green-950/40 dark:to-emerald-950/20">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-green-100 dark:bg-green-900/50">
              <Trophy className="h-5 w-5 text-green-700 dark:text-green-400" />
            </div>
            <div>
              <p className="text-sm font-bold text-green-800 dark:text-green-200">
                AI start/sit record: {recSummary.wins}-{recSummary.losses}
                {recSummary.ties > 0 ? `-${recSummary.ties}` : ""}
              </p>
              {recSummary.pending > 0 && (
                <p className="text-xs text-green-600 dark:text-green-400">
                  {recSummary.pending} call{recSummary.pending === 1 ? "" : "s"} pending this week&apos;s results
                </p>
              )}
            </div>
          </div>
        )}

        {/* ── Ask the AI ── */}
        <div className="mt-8">
          <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
            <MessageCircle className="h-3.5 w-3.5" />
            Ask the AI
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {quickAsks.map(({ q, icon: Icon }) => (
              <button
                key={q}
                onClick={() => router.push(`/chat?q=${encodeURIComponent(q)}`)}
                className="group flex items-center gap-3 rounded-xl border border-gray-200/60 bg-white p-4 text-left transition-all hover:border-green-300 hover:shadow-sm dark:border-gray-800/60 dark:hover:border-green-700/60"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-green-100 text-green-700 transition-colors group-hover:bg-green-600 group-hover:text-white dark:bg-green-900/50 dark:text-green-400">
                  <Icon className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-200">{q}</span>
              </button>
            ))}
          </div>
        </div>

        {/* ── Standings ── */}
        {standings && standings.length > 0 && (
          <div className="mt-8 overflow-hidden rounded-2xl border border-gray-200/60 bg-white dark:border-gray-800/60">
            <div className="flex items-center gap-2 border-b border-gray-100 px-6 py-4 dark:border-gray-800">
              <Crown className="h-4 w-4 text-gray-400" />
              <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                Standings
              </h2>
            </div>
            <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {standings.map((s, i) => {
                const isUser = s.team_id === roster?.team_id;
                return (
                  <div
                    key={s.team_id}
                    className={`flex items-center gap-4 px-6 py-3 transition-colors ${
                      isUser
                        ? "bg-green-50/70 dark:bg-green-950/30"
                        : "hover:bg-gray-50/50 dark:hover:bg-gray-800/30"
                    }`}
                  >
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                        i === 0
                          ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-400"
                          : i < 4
                            ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400"
                            : "bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500"
                      }`}
                    >
                      {i + 1}
                    </span>
                    <div className="flex-1">
                      <p className={`text-sm font-semibold ${isUser ? "text-green-700 dark:text-green-400" : "text-gray-900 dark:text-gray-100"}`}>
                        {s.owner_name ?? `Team ${s.team_id}`}
                        {isUser && <span className="ml-1.5 text-xs font-normal text-green-500">(you)</span>}
                      </p>
                    </div>
                    <span className="text-sm font-bold text-gray-700 dark:text-gray-200">
                      {formatRecord(s.wins, s.losses, s.ties)}
                    </span>
                    <span className="w-20 text-right text-xs text-gray-400">
                      {s.points_for.toFixed(1)} PF
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </main>
    </>
  );
}
