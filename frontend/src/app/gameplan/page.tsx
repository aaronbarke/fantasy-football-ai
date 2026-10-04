"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { EmptyState, LoadingState, ErrorState } from "@/components/PageState";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import PlayerAvatar from "@/components/PlayerAvatar";
import { injuryTextColor, positionColor } from "@/lib/utils";
import { ArrowRightLeft, Sparkles } from "lucide-react";
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
  bye?: boolean;
  // How the projection was built (see projection_service):
  //   model = base + matchup + vegas + weather + teammates out + QB change
  //   projected = s * Sleeper + (1 - s) * model + opposing D injuries
  base_ppg?: number | null;
  matchup_adj: number | null;
  vegas_adj: number | null;
  weather_adj?: number | null;
  opportunity_adj?: number | null;
  qb_adj?: number | null;
  model_proj?: number | null;
  external_proj?: number | null;
  blend_weight?: number | null;
  defense_injury_adj?: number | null;
  boost_reason?: string | null;
  qb_reason?: string | null;
  defense_reason?: string | null;
}

function signed(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}`;
}

/** Expandable "how we got this number" breakdown under a player row. */
function ProjectionMath({ p }: { p: PlanPlayer }) {
  if (p.projected == null || p.bye) return null;
  const status = (p.injury_status ?? "").toLowerCase();
  if (p.projected === 0 && status && status !== "active" && status !== "questionable") {
    return (
      <details className="group mt-2 text-xs">
        <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          How we got 0
        </summary>
        <p className="mt-2 rounded-md bg-gray-50 p-2.5 text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
          Ruled out ({p.injury_status}), so he projects 0 this week.
        </p>
      </details>
    );
  }
  const hasModel = p.model_proj != null && p.base_ppg != null;
  const hasSleeper = p.external_proj != null;
  const notes = [p.boost_reason, p.qb_reason, p.defense_reason].filter(
    (n): n is string => !!n,
  );
  if (!hasModel && !hasSleeper && notes.length === 0) return null;

  const terms: [string, number | null | undefined][] = [
    ["Matchup", p.matchup_adj],
    ["Vegas team total", p.vegas_adj],
    ["Weather", p.weather_adj],
    ["Teammates out", p.opportunity_adj],
    ["QB change", p.qb_adj],
  ];
  const s = p.blend_weight ?? (hasModel ? 0 : 1);
  const defense = p.defense_injury_adj ?? 0;

  return (
    <details className="group mt-2 text-xs">
      <summary className="cursor-pointer select-none text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
        How we got {p.projected}
      </summary>
      <div className="mt-2 space-y-1 rounded-md bg-gray-50 p-2.5 tabular-nums text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
        {hasModel && (
          <>
            <div className="flex justify-between font-semibold">
              <span>Our model</span>
              <span>{p.model_proj!.toFixed(1)}</span>
            </div>
            <div className="flex justify-between pl-3">
              <span>Recent-weighted average</span>
              <span>{p.base_ppg!.toFixed(1)}</span>
            </div>
            {terms
              .filter(([, v]) => v != null && Math.abs(v) >= 0.05)
              .map(([label, v]) => (
                <div key={label} className="flex justify-between pl-3">
                  <span>{label}</span>
                  <span>{signed(v!)}</span>
                </div>
              ))}
          </>
        )}
        {hasSleeper && (
          <div className="flex justify-between font-semibold">
            <span>Sleeper projection</span>
            <span>{p.external_proj!.toFixed(1)}</span>
          </div>
        )}
        {(hasModel || hasSleeper) && (
        <div className="border-t border-gray-200 pt-1 dark:border-gray-700">
          {hasModel && hasSleeper
            ? `Blend: ${Math.round(s * 100)}% Sleeper + ${Math.round((1 - s) * 100)}% our model` +
              (Math.abs(defense) >= 0.05 ? `, ${signed(defense)} opposing D injuries` : "") +
              ` = ${p.projected}`
            : hasSleeper
              ? `Too little history for our model, so this is Sleeper's number.`
              : `No Sleeper projection, so this is our model` +
                (Math.abs(defense) >= 0.05 ? ` ${signed(defense)} opposing D injuries` : "") +
                "."}
        </div>
        )}
        {notes.map((n) => (
          <p key={n} className="text-gray-500 dark:text-gray-400">
            {n}
          </p>
        ))}
      </div>
    </details>
  );
}

interface GamePlan {
  status: "ok" | "empty_roster";
  projected_total?: number;
  lineup?: { slot: string; player: PlanPlayer | null }[];
  bench?: PlanPlayer[];
  swaps?: {
    start: PlanPlayer;
    sit: PlanPlayer | null;
    slot: string;
    gain?: number | null;
    close?: boolean;
    reason?: string | null;
  }[];
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
  const color = pct >= 60 ? "#10b981" : pct >= 45 ? "#d97706" : "#dc2626";
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
        <p className="text-3xl font-semibold tracking-tight" style={{ color }}>
          {pct}%
        </p>
        <p className="text-xs font-medium text-gray-400">
          win prob
        </p>
      </div>
    </div>
  );
}

function ProjBar({ p }: { p: PlanPlayer }) {
  if (p.projected == null || p.ceiling == null || p.floor == null) return null;
  const max = Math.max(p.ceiling, 1);
  return (
    <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
      <div
        className="bg-gray-300 dark:bg-gray-600"
        style={{ width: `${(p.floor / max) * 100}%` }}
      />
      <div
        className="bg-accent"
        style={{ width: `${((p.projected - p.floor) / max) * 100}%` }}
      />
      <div
        className="bg-accent/25"
        style={{ width: `${((p.ceiling - p.projected) / max) * 100}%` }}
      />
    </div>
  );
}

function PlayerRow({ p, slot }: { p: PlanPlayer | null; slot?: string }) {
  if (!p)
    return (
      <div className="flex items-center gap-3 rounded-lg border border-dashed border-gray-300 p-3 text-sm text-gray-400 dark:border-gray-700">
        {slot && (
          <span className="w-10 text-xs font-bold text-gray-400">{slot}</span>
        )}
        No player available
      </div>
    );
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 transition-shadow hover:shadow-md">
      <div className="flex items-center gap-3">
        {slot && (
          <span className="w-10 shrink-0 text-xs font-bold text-gray-400">
            {slot}
          </span>
        )}
        <div className="flex shrink-0 items-center gap-2">
          <span
            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
          >
            {p.position}
          </span>
          <PlayerAvatar
            id={p.id}
            name={p.name}
            position={p.position}
            team={p.team}
            size={34}
          />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">
            {p.name}
            {p.injury_status && (
              <span className={`ml-2 text-xs font-medium ${injuryTextColor(p.injury_status)}`}>
                {p.injury_status}
              </span>
            )}
          </p>
          <p className="text-xs text-gray-500">
            {p.team ?? "FA"}
            {p.bye ? " · BYE" : p.opponent ? ` vs ${p.opponent}` : ""}
            {p.confidence && !p.bye ? ` · ${p.confidence} confidence` : ""}
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
      <ProjectionMath p={p} />
    </div>
  );
}

export default function GamePlanPage() {
  const { league } = useLeague();
  const [brief, setBrief] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const {
    data: plan,
    isLoading,
    error: loadError,
    refetch,
  } = useQuery({
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
      const resp = await api<{ analysis: string }>(
        `/api/gameplan/${league.id}/brief`,
        {
          method: "POST",
        },
      );
      setBrief(resp.analysis);
    } catch (err) {
      setBrief(
        `Something went wrong: ${err instanceof Error ? err.message : "unknown"}`,
      );
    } finally {
      setBusy(false);
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
        <div className="page-heading">
          <div>
            <p className="eyebrow">Your weekly edge</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Your game plan.
            </h1>
            <p className="page-description">
              A clearer view of your lineup, the close calls, and the matchup
              ahead.
            </p>
          </div>
          {plan?.status === "ok" && (
            <button
              onClick={getBrief}
              disabled={busy}
              className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition-colors hover:bg-accent-hover disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" />
              {busy ? "Writing your brief…" : "Explain my game plan"}
            </button>
          )}
        </div>

        {isLoading && <LoadingState label="Building your game plan…" />}
        {loadError && (
          <ErrorState
            message="Your game plan couldn’t load. Try again in a moment."
            retry={() => void refetch()}
          />
        )}

        {plan?.status === "empty_roster" && (
          <EmptyState
            title="Your lineup starts here"
            description="Once your league has a roster, refresh it from Overview to explore your game plan. Preparing for draft day? Your draft room is ready."
            href="/draft"
            action="Open draft room"
          />
        )}

        {plan?.status === "ok" && (
          <>
            {/* Scoreboard strip */}
            <div className="mt-6 grid gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-gray-200 bg-white p-5 text-center">
                <p className="text-xs font-medium text-gray-400">
                  Projected score
                </p>
                <p className="mt-1 font-mono text-4xl font-semibold tracking-tight text-accent">
                  {plan.projected_total}
                </p>
              </div>
              {plan.opponent ? (
                <>
                  <div className="flex items-center justify-center rounded-xl border border-gray-200 bg-white p-5">
                    <WinDial probability={plan.opponent.win_probability} />
                  </div>
                  <div className="rounded-xl border border-gray-200 bg-white p-5 text-center">
                    <p className="text-xs font-medium text-gray-400">
                      {plan.opponent.name ?? "Opponent"} · Wk{" "}
                      {plan.opponent.week}
                    </p>
                    <p className="mt-1 text-4xl font-semibold tracking-tight text-gray-400">
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
                  {plan.swaps.length} lineup change
                  {plan.swaps.length > 1 ? "s" : ""} to consider
                </p>
                <ul className="mt-2 space-y-1 text-sm text-amber-900 dark:text-amber-100/80">
                  {plan.swaps.map((s, i) => (
                    <li key={i}>
                      Start <strong>{s.start.name}</strong> ({s.start.projected}{" "}
                      proj)
                      {s.sit && (
                        <>
                          {" "}
                          over <strong>{s.sit.name}</strong> ({s.sit.projected}{" "}
                          proj)
                        </>
                      )}{" "}
                      at {s.slot}
                      {s.close && (
                        <span className="ml-1 text-xs font-medium text-amber-700/80 dark:text-amber-200/70">
                          (narrow{s.reason ? `, edge: ${s.reason}` : " call"})
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {brief && (
              <div className="prose-sm mt-6 rounded-xl callout p-6 text-sm leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {brief}
                </ReactMarkdown>
              </div>
            )}

            <div className="mt-6 grid gap-8 lg:grid-cols-2">
              <section>
                <h2 className="text-sm font-semibold text-gray-900">
                  Suggested lineup
                </h2>
                <div className="mt-3 space-y-2">
                  {plan.lineup?.map((s, i) => (
                    <PlayerRow
                      key={`${s.slot}-${i}`}
                      p={s.player}
                      slot={s.slot}
                    />
                  ))}
                </div>
              </section>
              <section>
                <h2 className="text-sm font-semibold text-gray-900">
                  Your bench
                </h2>
                <div className="mt-3 space-y-2">
                  {plan.bench?.map((p) => (
                    <PlayerRow key={p.id} p={p} />
                  ))}
                  {(plan.bench ?? []).length === 0 && (
                    <p className="text-sm text-gray-400">
                      No bench players with projections.
                    </p>
                  )}
                </div>
              </section>
            </div>

            <p className="mt-6 text-center text-xs text-gray-400">
              Bars show floor → projection → ceiling. Projections blend two
              seasons of production with opponent defense-vs-position data and
              Vegas implied totals.
            </p>
          </>
        )}
      </main>
    </>
  );
}
