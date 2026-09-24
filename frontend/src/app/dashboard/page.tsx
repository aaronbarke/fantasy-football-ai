"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";
import InjuryBadge from "@/components/InjuryBadge";
import PlayerAvatar from "@/components/PlayerAvatar";
import { api } from "@/lib/api";
import type { Matchup, Roster, StandingsEntry } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { formatRecord, positionColor, timeAgo } from "@/lib/utils";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  Crown,
  Database,
  MessageCircle,
  RefreshCw,
  Shield,
  Swords,
  Target,
  TrendingUp,
  Trophy,
  Zap,
} from "lucide-react";
import { useState } from "react";

const quickAsks = [
  { q: "Who should I start this week?", icon: Target, tone: "tone-blue" },
  { q: "Who should I pick up off waivers?", icon: TrendingUp, tone: "tone-emerald" },
  { q: "Break down my matchup this week", icon: Swords, tone: "tone-rose" },
];

/* ── Design-system primitives ── */

function SectionLabel({
  icon: Icon,
  tone = "tone-blue",
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`${tone} flex items-center gap-2 text-[13px] font-medium text-gray-600`}>
      {Icon && (
        <span className="tone-chip h-6 w-6 !rounded-md">
          <Icon className="h-3.5 w-3.5" />
        </span>
      )}
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
}) {
  return (
    <div className={`${tone} relative px-5 py-4`}>
      <span className="absolute inset-x-5 top-0 h-0.5 rounded-b-full bg-[rgb(var(--tone))]" />
      <p className="flex items-center justify-between text-[13px] font-medium text-gray-500">
        {label}
        <span className="tone-chip h-7 w-7 !rounded-lg">
          <Icon className="h-3.5 w-3.5" />
        </span>
      </p>
      <p className="mt-1 font-mono text-[26px] font-semibold leading-none tracking-tight text-gray-900 dark:text-gray-100">
        {value}
      </p>
      {sub && <p className="mt-1.5 text-xs tabular-nums text-gray-400">{sub}</p>}
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { league } = useLeague();
  const [syncing, setSyncing] = useState(false);
  const [refreshingStats, setRefreshingStats] = useState(false);

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
    queryFn: () =>
      api<StandingsEntry[]>(`/api/leagues/${league!.id}/standings`),
    enabled: !!league,
  });

  const { data: recSummary } = useQuery({
    queryKey: ["rec-summary", league?.id],
    queryFn: () =>
      api<{ wins: number; losses: number; ties: number; pending: number }>(
        `/api/recommendations/summary?connection_id=${league!.id}`,
      ),
    enabled: !!league,
  });

  // ESPN's injury feed also lists players cleared to play as "Active".
  const injured =
    roster &&
    [...roster.starters, ...roster.bench].filter(
      (p) => p.injury_status && p.injury_status.toLowerCase() !== "active",
    );

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

  async function refreshStats() {
    setRefreshingStats(true);
    try {
      await api(`/api/admin/refresh-stats`, { method: "POST" });
      window.location.reload();
    } finally {
      setRefreshingStats(false);
    }
  }

  return (
    <>
      <Navbar />
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto max-w-6xl px-4 py-8"
      >
        {/* ── Header: identity + quiet controls ── */}
        <div className="page-heading">
          <div>
            <p className="eyebrow">
              {league
                ? `${league.platform.charAt(0).toUpperCase()}${league.platform.slice(1)} · ${league.season} season`
                : "Your team at a glance"}
            </p>
            <h1>
              {league?.league_name ?? "Your overview"}
            </h1>
            {roster && (
              <p className="mt-1 text-sm text-gray-500">
                {roster.owner_name ?? "Your team"}
                {rank ? ` · ranked #${rank} of ${totalTeams}` : ""}
              </p>
            )}
          </div>

          <div className="flex flex-col items-stretch gap-1 self-start sm:items-end">
            <div className="flex items-center gap-2">
              <button
                onClick={syncNow}
                disabled={syncing}
                title="Re-sync this league's rosters, standings, and matchups"
                className="button-secondary"
              >
                <RefreshCw
                  className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`}
                />
                Refresh league
              </button>
              <button
                onClick={refreshStats}
                disabled={refreshingStats}
                title="Re-pull this week's NFL stats. Refreshes values, projections, and schedule strength"
                className="button-secondary"
              >
                <Database
                  className={`h-4 w-4 ${refreshingStats ? "animate-pulse" : ""}`}
                />
                {refreshingStats ? "Refreshing…" : "Refresh stats"}
              </button>
            </div>
            {league?.last_synced_at && (
              <p className="flex items-center gap-1.5 text-xs text-gray-400 sm:justify-end">
                <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                Synced {timeAgo(league.last_synced_at)}
              </p>
            )}
          </div>
        </div>

        {/* ── Metric ribbon: the team's vitals ── */}
        {rosterLoading ? (
          <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-gray-200/70 bg-white dark:border-gray-800/70 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="px-5 py-4">
                <div className="skeleton h-3 w-12" />
                <div className="skeleton mt-2 h-7 w-16" />
              </div>
            ))}
          </div>
        ) : roster ? (
          <div className="mt-6 grid grid-cols-2 divide-y divide-gray-100 overflow-hidden rounded-2xl border border-gray-200/70 bg-white dark:divide-gray-800/70 dark:border-gray-800/70 sm:grid-cols-4 sm:divide-y-0 sm:divide-x">
            <Stat
              label="Record"
              icon={Trophy}
              tone="tone-blue"
              value={formatRecord(roster.wins, roster.losses, roster.ties)}
              sub={games > 0 ? `${games} games` : "preseason"}
            />
            <Stat
              label="Rank"
              icon={Crown}
              tone="tone-violet"
              value={rank ? `#${rank}` : "—"}
              sub={totalTeams ? `of ${totalTeams}` : undefined}
            />
            <Stat
              label="Points for"
              icon={TrendingUp}
              tone="tone-emerald"
              value={roster.points_for.toFixed(1)}
              sub={ppg ? `${ppg.toFixed(1)} / gm` : undefined}
            />
            <Stat
              label="Points against"
              icon={Shield}
              tone="tone-rose"
              value={roster.points_against.toFixed(1)}
            />
          </div>
        ) : (
          <div className="mt-6 rounded-2xl border border-gray-200/70 bg-white px-6 py-8 text-center dark:border-gray-800/70">
            <p className="text-sm text-gray-400">
              Your roster will appear here. Refresh your league to check for
              players.
            </p>
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
            <SectionLabel icon={Swords} tone="tone-rose">
              {matchup?.week ? `Week ${matchup.week} matchup` : "This week"}
            </SectionLabel>
            {matchup?.opponent_team ? (
              <div className="mt-5">
                <div className="flex items-center justify-between">
                  <div className="flex-1 text-center">
                    <p className="text-xs font-medium text-gray-500">You</p>
                    <p className="mt-1.5 font-mono text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
                      {formatRecord(
                        roster?.wins ?? 0,
                        roster?.losses ?? 0,
                        roster?.ties ?? 0,
                      )}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                      {roster?.points_for.toFixed(1)} PF
                    </p>
                  </div>
                  <span className="rounded-full border border-gray-200 px-2 py-0.5 font-mono text-[10px] font-medium text-gray-400">
                    VS
                  </span>
                  <div className="flex-1 text-center">
                    <p className="truncate text-xs font-medium text-gray-500">
                      {matchup.opponent_team.owner_name ?? "Opp"}
                    </p>
                    <p className="mt-1.5 font-mono text-3xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">
                      {formatRecord(
                        matchup.opponent_team.wins,
                        matchup.opponent_team.losses,
                        matchup.opponent_team.ties,
                      )}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-gray-400">
                      {matchup.opponent_team.points_for.toFixed(1)} PF
                    </p>
                  </div>
                </div>
                <Link
                  href="/matchup"
                  className="button-secondary mt-6 w-full"
                >
                  See the matchup <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
            ) : (
              <div className="mt-6 flex flex-col items-center py-6 text-gray-400">
                <Swords className="h-8 w-8 stroke-1" />
                <p className="mt-2 text-sm">
                  Your next matchup will appear here.
                </p>
              </div>
            )}
          </div>

          {/* Right column: Game Plan CTA + injuries */}
          <div className="flex flex-col gap-6">
            {/* Game Plan — the accent moment */}
            <Link
              href="/gameplan"
              className="stage group flex items-center gap-4 rounded-2xl p-5 transition-transform hover:-translate-y-0.5"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-signal ring-1 ring-white/10">
                <Zap className="h-5 w-5" />
              </div>
              <div className="flex-1">
                <p className="text-base font-semibold">Your weekly game plan</p>
                <p className="mt-0.5 text-sm text-zinc-400">
                  Your lineup, the close calls, and what comes next.
                </p>
              </div>
              <ArrowRight className="h-5 w-5 shrink-0 transition-transform group-hover:translate-x-0.5" />
            </Link>

            {/* Injury report */}
            <div className="flex-1 rounded-2xl border border-gray-200/70 bg-white p-6 dark:border-gray-800/70">
              <SectionLabel icon={Activity} tone="tone-amber">Injury report</SectionLabel>
              {injured && injured.length > 0 ? (
                <ul className="mt-4 space-y-3">
                  {injured.slice(0, 4).map((p) => (
                    <li key={p.id} className="flex items-center gap-3">
                      <div className="flex shrink-0 items-center gap-2">
                        <span
                          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white ${positionColor(p.position)}`}
                        >
                          {p.position}
                        </span>
                        <PlayerAvatar
                          id={p.id}
                          name={p.name}
                          position={p.position}
                          team={p.team}
                          size={32}
                        />
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
                  All clear. No injuries on your roster.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── AI record ── */}
        {recSummary &&
          recSummary.wins + recSummary.losses + recSummary.pending > 0 && (
            <div className="mt-6 flex items-center gap-4 rounded-2xl border border-gray-200/70 bg-white px-6 py-4 dark:border-gray-800/70">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft">
                <Trophy className="h-5 w-5 text-accent" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                  AI start/sit record:{" "}
                  <span className="font-mono">
                    {recSummary.wins}-{recSummary.losses}
                    {recSummary.ties > 0 ? `-${recSummary.ties}` : ""}
                  </span>
                </p>
                {recSummary.pending > 0 && (
                  <p className="text-xs text-gray-500">
                    {recSummary.pending} call
                    {recSummary.pending === 1 ? "" : "s"} pending this
                    week&apos;s results
                  </p>
                )}
              </div>
            </div>
          )}

        {/* ── Ask the AI ── */}
        <div className="mt-8">
          <SectionLabel icon={MessageCircle} tone="tone-violet">Ask the AI</SectionLabel>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {quickAsks.map(({ q, icon: Icon, tone }) => (
              <button
                key={q}
                onClick={() => router.push(`/chat?q=${encodeURIComponent(q)}`)}
                className={`${tone} group flex items-center gap-3 rounded-2xl border border-gray-200/70 bg-white p-4 text-left transition-all hover:-translate-y-0.5 hover:border-[rgb(var(--tone)/0.45)] hover:shadow-[0_0_0_3px_rgb(var(--tone)/0.1)] dark:border-gray-800/70`}
              >
                <div className="tone-chip h-9 w-9">
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
              <SectionLabel icon={Crown} tone="tone-amber">Standings</SectionLabel>
            </div>
            <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {standings.map((s, i) => {
                const isUser = s.team_id === roster?.team_id;
                return (
                  <div
                    key={s.team_id}
                    className={`flex items-center gap-4 px-6 py-3 transition-colors ${
                      isUser
                        ? "bg-accent-soft/60 shadow-[inset_2px_0_0_rgb(var(--accent))]"
                        : "hover:bg-gray-50/50 dark:hover:bg-gray-800/30"
                    }`}
                  >
                    <span
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg font-mono text-xs font-semibold ${
                        i === 0
                          ? "bg-signal text-zinc-900"
                          : "bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500"
                      }`}
                    >
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p
                        className={`truncate text-sm font-semibold ${
                          isUser
                            ? "text-accent-ink"
                            : "text-gray-900 dark:text-gray-100"
                        }`}
                      >
                        {s.owner_name ?? `Team ${s.team_id}`}
                        {isUser && (
                          <span className="ml-2 rounded-full bg-accent px-1.5 py-px text-[10px] font-semibold text-accent-fg">
                            You
                          </span>
                        )}
                      </p>
                    </div>
                    <span className="font-mono text-sm font-medium text-gray-700 dark:text-gray-200">
                      {formatRecord(s.wins, s.losses, s.ties)}
                    </span>
                    <span className="w-20 text-right font-mono text-xs text-gray-400">
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
