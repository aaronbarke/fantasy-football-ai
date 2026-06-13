"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import PlayerAvatar from "@/components/PlayerAvatar";
import { positionColor } from "@/lib/utils";
import { ArrowRightLeft, ClipboardList, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface PlanPlayer {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  injury_status: string | null;
  projected: number | null;
  floor: number | null;
  ceiling: number | null;
  confidence: string | null;
  opponent: string | null;
  matchup_adj: number | null;
  vegas_adj: number | null;
}

interface GamePlan {
  status: "ok" | "empty_roster";
  projected_total?: number;
  lineup?: { slot: string; player: PlanPlayer | null }[];
  bench?: PlanPlayer[];
  swaps?: { start: PlanPlayer; sit: PlanPlayer | null; slot: string }[];
  opponent?: {
    name: string | null;
    projected_total: number;
    win_probability: number;
    week: number;
  } | null;
}

function WinDial({ probability }: { probability: number }) {
  const pct = Math.round(probability * 100);
  const r = 52;
  const circumference = Math.PI * r; // semicircle
  const filled = circumference * probability;
  const color = pct >= 60 ? "#16a34a" : pct >= 45 ? "#d97706" : "#dc2626";
  return (
    <div className="relative flex flex-col items-center">
      <svg width="140" height="84" viewBox="0 0 140 84">
        <path
          d="M 14 76 A 56 56 0 0 1 126 76"
          fill="none"
          stroke="currentColor"
          className="text-gray-200 dark:text-gray-700"
          strokeWidth="12"
          strokeLinecap="round"
        />
        <path
          d="M 14 76 A 56 56 0 0 1 126 76"
          fill="none"
          stroke={color}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${(filled / circumference) * 176} 176`}
        />
      </svg>
      <div className="absolute bottom-0 text-center">
        <p className="text-3xl font-extrabold" style={{ color }}>
          {pct}%
        </p>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">win prob</p>
      </div>
    </div>
  );
}

function ProjBar({ p }: { p: PlanPlayer }) {
  if (p.projected == null || p.ceiling == null || p.floor == null) return null;
  const max = Math.max(p.ceiling, 1);
  return (
    <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
      <div className="bg-gray-300 dark:bg-gray-600" style={{ width: `${(p.floor / max) * 100}%` }} />
      <div className="bg-green-500" style={{ width: `${((p.projected - p.floor) / max) * 100}%` }} />
      <div className="bg-green-200 dark:bg-green-900" style={{ width: `${((p.ceiling - p.projected) / max) * 100}%` }} />
    </div>
  );
}

function PlayerRow({ p, slot }: { p: PlanPlayer | null; slot?: string }) {
  if (!p)
    return (
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-gray-300 p-3 text-sm text-gray-400 dark:border-gray-700">
        {slot && <span className="w-10 text-xs font-bold text-gray-400">{slot}</span>}
        No player available
      </div>
    );
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 transition-shadow hover:shadow-md">
      <div className="flex items-center gap-3">
        {slot && (
          <span className="w-10 shrink-0 text-xs font-bold text-gray-400">{slot}</span>
        )}
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
          >
            {p.position}
          </span>
          <PlayerAvatar id={p.id} name={p.name} position={p.position} team={p.team} size={34} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">
            {p.name}
            {p.injury_status && (
              <span className="ml-2 text-xs font-medium text-red-500">
                {p.injury_status}
              </span>
            )}
          </p>
          <p className="text-xs text-gray-500">
            {p.team ?? "FA"}
            {p.opponent ? ` vs ${p.opponent}` : ""}
            {p.confidence ? ` · ${p.confidence} confidence` : ""}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold">{p.projected ?? "—"}</p>
          <p className="text-[10px] text-gray-400">
            {p.floor}–{p.ceiling}
          </p>
        </div>
      </div>
      <ProjBar p={p} />
    </div>
  );
}

export default function GamePlanPage() {
  const { league } = useLeague();
  const [brief, setBrief] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data: plan, isLoading } = useQuery({
    queryKey: ["gameplan", league?.id],
    queryFn: () => api<GamePlan>(`/api/gameplan/${league!.id}`),
    enabled: !!league,
    staleTime: 10 * 60_000,
  });

  async function getBrief() {
    if (!league) return;
    setBusy(true);
    setBrief(null);
    try {
      const resp = await api<{ analysis: string }>(`/api/gameplan/${league.id}/brief`, {
        method: "POST",
      });
      setBrief(resp.analysis);
    } catch (err) {
      setBrief(`Something went wrong: ${err instanceof Error ? err.message : "unknown"}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold">
              <ClipboardList className="h-6 w-6 text-green-600" />
              Weekly game plan
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Model-optimal lineup, projected score, and win odds — built from
              projections, matchups, and Vegas lines.
            </p>
          </div>
          {plan?.status === "ok" && (
            <button
              onClick={getBrief}
              disabled={busy}
              className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-green-700 disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" />
              {busy ? "Writing the brief…" : "AI coach's brief"}
            </button>
          )}
        </div>

        {isLoading && <p className="mt-6 text-sm text-gray-400">Building your game plan…</p>}

        {plan?.status === "empty_roster" && (
          <div className="mt-10 rounded-xl border border-dashed border-gray-300 p-10 text-center dark:border-gray-700">
            <p className="text-lg font-semibold">Your game plan unlocks after draft day</p>
            <p className="mx-auto mt-2 max-w-md text-sm text-gray-500">
              Once your league drafts and you hit Sync, this page builds your
              optimal lineup, projects your score, and computes win odds every
              week. Until then, prep with the Draft assistant under Tools.
            </p>
          </div>
        )}

        {plan?.status === "ok" && (
          <>
            {/* Scoreboard strip */}
            <div className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-gray-200 bg-white p-5 text-center">
                <p className="text-xs uppercase tracking-wide text-gray-400">
                  Projected score
                </p>
                <p className="mt-1 text-4xl font-extrabold text-green-700">
                  {plan.projected_total}
                </p>
              </div>
              {plan.opponent ? (
                <>
                  <div className="flex items-center justify-center rounded-xl border border-gray-200 bg-white p-5">
                    <WinDial probability={plan.opponent.win_probability} />
                  </div>
                  <div className="rounded-xl border border-gray-200 bg-white p-5 text-center">
                    <p className="text-xs uppercase tracking-wide text-gray-400">
                      {plan.opponent.name ?? "Opponent"} · Wk {plan.opponent.week}
                    </p>
                    <p className="mt-1 text-4xl font-extrabold text-gray-400">
                      {plan.opponent.projected_total}
                    </p>
                  </div>
                </>
              ) : (
                <div className="rounded-xl border border-gray-200 bg-white p-5 text-center sm:col-span-2">
                  <p className="mt-3 text-sm text-gray-400">
                    Win probability appears once weekly matchups are synced.
                  </p>
                </div>
              )}
            </div>

            {/* Swap alerts */}
            {plan.swaps && plan.swaps.length > 0 && (
              <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-5 dark:border-amber-500/25 dark:bg-amber-500/10">
                <p className="flex items-center gap-2 text-sm font-bold text-amber-800 dark:text-amber-300">
                  <ArrowRightLeft className="h-4 w-4" />
                  {plan.swaps.length} lineup change{plan.swaps.length > 1 ? "s" : ""} recommended
                </p>
                <ul className="mt-2 space-y-1 text-sm text-amber-900 dark:text-amber-100/80">
                  {plan.swaps.map((s, i) => (
                    <li key={i}>
                      Start <strong>{s.start.name}</strong> ({s.start.projected} proj)
                      {s.sit && (
                        <>
                          {" "}over <strong>{s.sit.name}</strong> ({s.sit.projected} proj)
                        </>
                      )}{" "}
                      at {s.slot}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {brief && (
              <div className="prose-sm mt-6 rounded-xl border border-green-200 bg-green-50 p-6 text-sm leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{brief}</ReactMarkdown>
              </div>
            )}

            <div className="mt-6 grid gap-8 lg:grid-cols-2">
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Optimal lineup
                </h2>
                <div className="mt-3 space-y-2">
                  {plan.lineup?.map((s, i) => (
                    <PlayerRow key={`${s.slot}-${i}`} p={s.player} slot={s.slot} />
                  ))}
                </div>
              </section>
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Bench (by projection)
                </h2>
                <div className="mt-3 space-y-2">
                  {plan.bench?.map((p) => <PlayerRow key={p.id} p={p} />)}
                  {(plan.bench ?? []).length === 0 && (
                    <p className="text-sm text-gray-400">No bench players with projections.</p>
                  )}
                </div>
              </section>
            </div>

            <p className="mt-6 text-center text-xs text-gray-400">
              Bars show floor → projection → ceiling. Projections blend two seasons
              of production with opponent defense-vs-position data and Vegas
              implied totals.
            </p>
          </>
        )}
      </main>
    </>
  );
}
