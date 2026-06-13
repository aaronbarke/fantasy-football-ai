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
  Swords,
  Target,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";
import { useState } from "react";

const quickAsks = [
  { q: "Who should I start this week?", icon: Target },
  { q: "Who should I pick up off waivers?", icon: TrendingUp },
  { q: "Break down my matchup this week", icon: Swords },
];

/* ── Design-system primitives ── */

function SectionLabel({
  icon: Icon,
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-400">
      {Icon && <Icon className="h-3.5 w-3.5" />}
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="px-4 py-4 text-center">
      <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-extrabold tabular-nums text-gray-900 dark:text-gray-100">
        {value}
      </p>
      {sub && <p className="mt-0.5 text-[11px] tabular-nums text-gray-400">{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { league } = useLeague();
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
  const games = roster ? roster.wins + roster.losses + roster.ties : 0;
  const ppg = roster && games > 0 ? roster.points_for / games : null;

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
        {/* ── Header: identity + quiet controls ── */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-green-600 dark:text-green-400">
              {league ? `${league.platform} · ${league.season}` : "Loading"}
            </p>
            <h1 className="mt-1.5 text-3xl font-extrabold tracking-tight text-gray-900 dark:text-gray-100 sm:text-4xl">
              {league?.league_name ?? "Dashboard"}
            </h1>
            {roster && (
              <p className="mt-1 text-sm text-gray-500">
                {roster.owner_name ?? "Your team"}
                {rank ? ` · ranked #${rank} of ${totalTeams}` : ""}
              </p>
            )}
          </div>

          <button
            onClick={syncNow}
            disabled={syncing}
            className="flex items-center gap-1.5 self-start rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            Sync
          </button>
        </div>

        {/* ── Metric ribbon: the team's vitals ── */}
        {rosterLoading ? (
          <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-gray-200/70 bg-white dark:border-gray-800/70 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="px-4 py-4 text-center">
                <div className="skeleton mx-auto h-3 w-12" />
                <div className="skeleton mx-auto mt-2 h-7 w-16" />
              </div>
            ))}
          </div>
        ) : roster ? (
          <div className="mt-6 grid grid-cols-2 divide-y divide-gray-100 overflow-hidden rounded-2xl border border-gray-200/70 bg-white dark:divide-gray-800/70 dark:border-gray-800/70 sm:grid-cols-4 sm:divide-y-0 sm:divide-x">
            <Stat
              label="Record"
              value={formatRecord(roster.wins, roster.losses, roster.ties)}
              sub={games > 0 ? `${games} games` : "preseason"}
            />
            <Stat
              label="Rank"
              value={rank ? `#${rank}` : "—"}
              sub={totalTeams ? `of ${totalTeams}` : undefined}
            />
            <Stat
              label="Points for"
              value={roster.points_for.toFixed(1)}
              sub={ppg ? `${ppg.toFixed(1)} / gm` : undefined}
            />
            <Stat label="Points against" value={roster.points_against.toFixed(1)} />
          </div>
        ) : (
          <div className="mt-6 rounded-2xl border border-gray-200/70 bg-white px-6 py-8 text-center dark:border-gray-800/70">
            <p className="text-sm text-gray-400">No roster yet — try syncing your league.</p>
          </div>
        )}

        {/* Team claim banner */}
        {league && !league.team_id && standings && standings.length > 0 && (
          <div className="mt-4 flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-3 dark:border-amber-800/50 dark:bg-amber-950/30">
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

        {/* ── This week: matchup | (game plan + injuries) ── */}
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          {/* Matchup */}
          <div className="rounded-2xl border border-gray-200/70 bg-white p-6 dark:border-gray-800/70">
            <SectionLabel icon={Swords}>
              {matchup?.week ? `Week ${matchup.week} matchup` : "This week"}
            </SectionLabel>
            {matchup?.opponent_team ? (
              <div className="mt-5">
                <div className="flex items-center justify-between">
                  <div className="flex-1 text-center">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                      You
                    </p>
                    <p className="mt-1 text-2xl font-extrabold tabular-nums text-gray-900 dark:text-gray-100">
                      {formatRecord(roster?.wins ?? 0, roster?.losses ?? 0, roster?.ties ?? 0)}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                      {roster?.points_for.toFixed(1)} PF
                    </p>
                  </div>
                  <span className="px-3 text-xs font-bold text-gray-300 dark:text-gray-600">
                    VS
                  </span>
                  <div className="flex-1 text-center">
                    <p className="truncate text-[11px] font-medium uppercase tracking-wider text-gray-400">
                      {matchup.opponent_team.owner_name ?? "Opp"}
                    </p>
                    <p className="mt-1 text-2xl font-extrabold tabular-nums text-gray-900 dark:text-gray-100">
                      {formatRecord(
                        matchup.opponent_team.wins,
                        matchup.opponent_team.losses,
                        matchup.opponent_team.ties
                      )}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                      {matchup.opponent_team.points_for.toFixed(1)} PF
                    </p>
                  </div>
                </div>
                <Link
                  href="/matchup"
                  className="mt-5 flex items-center justify-center gap-1 rounded-lg bg-gray-100 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  Full breakdown <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
            ) : (
              <div className="mt-6 flex flex-col items-center py-6 text-gray-400">
                <Swords className="h-8 w-8 stroke-1" />
                <p className="mt-2 text-sm">No matchup data yet.</p>
              </div>
            )}
          </div>

          {/* Right column: Game Plan CTA + injuries */}
          <div className="flex flex-col gap-6">
            {/* Game Plan — the accent moment */}
            <Link
              href="/gameplan"
              className="group flex items-center gap-4 rounded-2xl bg-green-600 p-5 text-white shadow-md shadow-green-600/20 transition-all hover:bg-green-700"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
                <Zap className="h-6 w-6" />
              </div>
              <div className="flex-1">
                <p className="text-base font-bold">Weekly Game Plan</p>
                <p className="text-sm text-green-50/90">
                  Optimal lineup, projected score &amp; win odds.
                </p>
              </div>
              <ArrowRight className="h-5 w-5 shrink-0 transition-transform group-hover:translate-x-0.5" />
            </Link>

            {/* Injury report */}
            <div className="flex-1 rounded-2xl border border-gray-200/70 bg-white p-6 dark:border-gray-800/70">
              <SectionLabel icon={Activity}>Injury report</SectionLabel>
              {injured && injured.length > 0 ? (
                <ul className="mt-4 space-y-3">
                  {injured.slice(0, 4).map((p) => (
                    <li key={p.id} className="flex items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-[10px] font-bold text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                        {p.position}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
                          {p.name}
                        </p>
                        <p className="text-xs text-gray-400">{p.team}</p>
                      </div>
                      <InjuryBadge status={p.injury_status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
                  <Activity className="h-4 w-4" />
                  All clear — no injuries on your roster.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── AI record ── */}
        {recSummary && recSummary.wins + recSummary.losses + recSummary.pending > 0 && (
          <div className="mt-6 flex items-center gap-4 rounded-2xl border border-gray-200/70 bg-white px-6 py-4 dark:border-gray-800/70">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-green-100 dark:bg-green-900/40">
              <Trophy className="h-5 w-5 text-green-700 dark:text-green-400" />
            </div>
            <div>
              <p className="text-sm font-bold text-gray-900 dark:text-gray-100">
                AI start/sit record:{" "}
                <span className="tabular-nums">
                  {recSummary.wins}-{recSummary.losses}
                  {recSummary.ties > 0 ? `-${recSummary.ties}` : ""}
                </span>
              </p>
              {recSummary.pending > 0 && (
                <p className="text-xs text-gray-500">
                  {recSummary.pending} call{recSummary.pending === 1 ? "" : "s"} pending this
                  week&apos;s results
                </p>
              )}
            </div>
          </div>
        )}

        {/* ── Ask the AI ── */}
        <div className="mt-8">
          <SectionLabel icon={MessageCircle}>Ask the AI</SectionLabel>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {quickAsks.map(({ q, icon: Icon }) => (
              <button
                key={q}
                onClick={() => router.push(`/chat?q=${encodeURIComponent(q)}`)}
                className="group flex items-center gap-3 rounded-2xl border border-gray-200/70 bg-white p-4 text-left transition-all hover:border-green-300 hover:shadow-sm dark:border-gray-800/70 dark:hover:border-green-700/60"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-green-100 text-green-700 transition-colors group-hover:bg-green-600 group-hover:text-white dark:bg-green-900/40 dark:text-green-400">
                  <Icon className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
                  {q}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* ── Standings ── */}
        {standings && standings.length > 0 && (
          <div className="mt-8 overflow-hidden rounded-2xl border border-gray-200/70 bg-white dark:border-gray-800/70">
            <div className="border-b border-gray-100 px-6 py-4 dark:border-gray-800">
              <SectionLabel icon={Crown}>Standings</SectionLabel>
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
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums ${
                        i === 0
                          ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-400"
                          : "bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500"
                      }`}
                    >
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className={`truncate text-sm font-semibold ${
                          isUser
                            ? "text-green-700 dark:text-green-400"
                            : "text-gray-900 dark:text-gray-100"
                        }`}
                      >
                        {s.owner_name ?? `Team ${s.team_id}`}
                        {isUser && (
                          <span className="ml-1.5 text-xs font-normal text-green-500">
                            you
                          </span>
                        )}
                      </p>
                    </div>
                    <span className="text-sm font-bold tabular-nums text-gray-700 dark:text-gray-200">
                      {formatRecord(s.wins, s.losses, s.ties)}
                    </span>
                    <span className="w-20 text-right text-xs tabular-nums text-gray-400">
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
