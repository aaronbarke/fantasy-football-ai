"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import InjuryBadge from "@/components/InjuryBadge";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import PlayerAvatar from "@/components/PlayerAvatar";
import { Sparkles } from "lucide-react";

interface MPlayer {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  injury_status?: string | null;
  projected: number | null;
  confidence?: string | null;
  opponent?: string | null;
}
interface MRow {
  slot: string;
  user: MPlayer | null;
  opponent: MPlayer | null;
}
interface MTeam {
  owner_name: string | null;
  record: string;
  projected_total: number;
}
interface MatchupPreview {
  status: string;
  week?: number;
  win_probability?: number;
  user?: MTeam;
  opponent?: MTeam;
  rows?: MRow[];
}

function PlayerSide({ p, win, align }: { p: MPlayer | null; win: boolean; align: "left" | "right" }) {
  const right = align === "right";
  if (!p) {
    return (
      <div className={`flex flex-1 items-center gap-2 ${right ? "flex-row-reverse text-right" : ""}`}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gray-100 text-[10px] text-gray-400 dark:bg-gray-800">
          —
        </div>
        <span className="text-sm text-gray-400">No projection</span>
      </div>
    );
  }
  return (
    <div className={`flex flex-1 items-center gap-2.5 ${right ? "flex-row-reverse text-right" : ""}`}>
      <PlayerAvatar id={p.id} name={p.name} position={p.position} team={p.team} size={36} />
      <div className="min-w-0">
        <div className={`flex items-center gap-1.5 ${right ? "flex-row-reverse" : ""}`}>
          <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
            {p.name}
          </span>
          <InjuryBadge status={p.injury_status} />
        </div>
        <p className="text-xs text-gray-400">
          {p.team}
          {p.opponent ? ` · vs ${p.opponent}` : ""}
        </p>
      </div>
      <span
        className={`ml-auto shrink-0 text-base font-extrabold tabular-nums ${right ? "ml-0 mr-auto" : ""} ${
          win ? "text-green-600 dark:text-green-400" : "text-gray-400"
        }`}
      >
        {p.projected != null ? p.projected.toFixed(1) : "—"}
      </span>
    </div>
  );
}

export default function MatchupPage() {
  const { league } = useLeague();

  const { data, isLoading } = useQuery({
    queryKey: ["matchup-preview", league?.id],
    queryFn: () => api<MatchupPreview>(`/api/leagues/${league!.id}/matchup/preview`),
    enabled: !!league,
    retry: false,
  });

  const ready = data?.status === "ok" && data.user && data.opponent && data.rows;
  const winPct = data?.win_probability != null ? Math.round(data.win_probability * 100) : null;
  const oppName = data?.opponent?.owner_name || "Opponent";

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight">
            {data?.week ? `Week ${data.week} matchup` : "Matchup"}
          </h1>
          <Link
            href={`/chat?q=${encodeURIComponent("Break down my matchup this week")}`}
            className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
          >
            <Sparkles className="h-4 w-4" /> Ask AI to break it down
          </Link>
        </div>

        {isLoading && <p className="mt-6 text-sm text-gray-400">Projecting the matchup…</p>}
        {!isLoading && !ready && (
          <p className="mt-6 text-sm text-gray-400">
            No matchup data yet — projections appear once your league has rosters.
            Try Sync on the dashboard after draft day.
          </p>
        )}

        {ready && data.user && data.opponent && (
          <>
            {/* Scoreboard */}
            <div className="mt-6 rounded-2xl border border-gray-200/70 bg-white p-6 dark:border-gray-800/70">
              <div className="flex items-end justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-green-600 dark:text-green-400">
                    You · {data.user.record}
                  </p>
                  <p className="mt-1 text-4xl font-extrabold tabular-nums text-gray-900 dark:text-gray-100">
                    {data.user.projected_total.toFixed(1)}
                  </p>
                </div>
                <span className="pb-2 text-xs font-bold text-gray-300 dark:text-gray-600">
                  PROJECTED
                </span>
                <div className="text-right">
                  <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                    {oppName} · {data.opponent.record}
                  </p>
                  <p className="mt-1 text-4xl font-extrabold tabular-nums text-gray-900 dark:text-gray-100">
                    {data.opponent.projected_total.toFixed(1)}
                  </p>
                </div>
              </div>

              {/* Win probability bar */}
              {winPct != null && (
                <div className="mt-5">
                  <div className="mb-1 flex justify-between text-xs font-semibold">
                    <span className="text-green-600 dark:text-green-400">{winPct}% you</span>
                    <span className="text-gray-400">{100 - winPct}% {oppName}</span>
                  </div>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
                    <div
                      className="bg-green-500 transition-all"
                      style={{ width: `${winPct}%` }}
                    />
                  </div>
                  <p className="mt-2 text-center text-xs text-gray-400">
                    Win probability from projected scores &amp; each player&apos;s volatility
                  </p>
                </div>
              )}
            </div>

            {/* Position battles */}
            <div className="mt-6 space-y-2">
              {data.rows!.map((r, i) => {
                const u = r.user?.projected ?? -1;
                const o = r.opponent?.projected ?? -1;
                const userWin = u > o;
                const oppWin = o > u;
                return (
                  <div
                    key={i}
                    className="rounded-xl border border-gray-200/70 bg-white p-3 dark:border-gray-800/70"
                  >
                    <div className="mb-1.5 text-center text-[10px] font-bold uppercase tracking-widest text-gray-300 dark:text-gray-600">
                      {r.slot}
                    </div>
                    <div className="flex items-center gap-2">
                      <PlayerSide p={r.user} win={userWin} align="left" />
                      <div className="shrink-0 px-1 text-[10px] font-bold text-gray-300 dark:text-gray-700">
                        VS
                      </div>
                      <PlayerSide p={r.opponent} win={oppWin} align="right" />
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </main>
    </>
  );
}
