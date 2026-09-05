"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import { Play, RotateCcw, Trophy, Zap } from "lucide-react";

interface PoolPlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  bye_week: number | null;
  adp: number | null;
  vor: number;
  tier: number | null;
  overall_rank: number | null;
  adp_delta: number | null;
  value_score: number;
  proj_points: number;
}

interface Pick {
  overall_pick: number;
  round: number;
  team_slot: number;
  player_id: string;
  is_user: boolean;
  position: string | null;
  snapshot: PoolPlayer | null;
}

interface Recommendation extends PoolPlayer {
  score: number;
  reasons: string[];
}

interface MockState {
  id: string;
  teams: number;
  rounds: number;
  my_slot: number;
  scoring: string;
  status: string;
  picks_made: number;
  total_picks: number;
  on_the_clock: number | null;
  current_round: number | null;
  current_slot: number | null;
  is_my_turn: boolean;
  next_pick: number | null;
  following_pick: number | null;
  picks: Pick[];
  my_player_ids: string[];
  available?: PoolPlayer[];
  recommendations?: Recommendation[];
}

interface Results {
  your_rank: number;
  teams: number;
  your_total_vor: number;
  league_average_vor: number;
  standings: { team_slot: number; total_vor: number; is_you: boolean }[];
  best_pick: PoolPlayer | null;
  worst_pick: PoolPlayer | null;
  roster: (PoolPlayer | null)[];
}

const ACTIVE_KEY = "mock_draft_active_id";
const POSITIONS = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"];

export default function MockDraftPage() {
  const { league } = useLeague({ requireLeague: false });
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [teams, setTeams] = useState(12);
  const [rounds, setRounds] = useState(15);
  const [slot, setSlot] = useState(5);
  const [filter, setFilter] = useState("ALL");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [prefilled, setPrefilled] = useState(false);

  useEffect(() => {
    setDraftId(localStorage.getItem(ACTIVE_KEY));
    setLoaded(true);
  }, []);

  // Pre-fill the setup form from the connected league so the numbers on screen
  // match what the draft will actually use (14 teams / 17 rounds), instead of
  // the generic form defaults.
  const { data: config } = useQuery({
    queryKey: ["mockConfig", league?.id],
    queryFn: () =>
      api<{ teams: number | null; rounds: number | null; scoring: string | null }>(
        `/api/mock/config?connection_id=${league!.id}`
      ),
    enabled: !!league?.id && !draftId,
  });

  useEffect(() => {
    if (config && !prefilled) {
      if (config.teams) setTeams(config.teams);
      if (config.rounds) setRounds(config.rounds);
      setPrefilled(true);
    }
  }, [config, prefilled]);

  const { data: state, isLoading } = useQuery({
    queryKey: ["mock", draftId],
    queryFn: () => api<MockState>(`/api/mock/${draftId}`),
    enabled: !!draftId,
  });

  const { data: results } = useQuery({
    queryKey: ["mockResults", draftId],
    queryFn: () => api<Results>(`/api/mock/${draftId}/results`),
    enabled: !!draftId && state?.status === "complete",
  });

  async function startDraft() {
    setBusy(true);
    setError(null);
    try {
      const created = await api<MockState>("/api/mock", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league?.id ?? null,
          teams,
          rounds,
          my_slot: slot,
        }),
      });
      localStorage.setItem(ACTIVE_KEY, created.id);
      setDraftId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the draft");
    } finally {
      setBusy(false);
    }
  }

  async function pick(playerId: string) {
    if (!draftId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/mock/${draftId}/pick`, {
        method: "POST",
        body: JSON.stringify({ player_id: playerId }),
      });
      await queryClient.invalidateQueries({ queryKey: ["mock", draftId] });
      await queryClient.invalidateQueries({ queryKey: ["mockResults", draftId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "That pick didn't go through");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    localStorage.removeItem(ACTIVE_KEY);
    setDraftId(null);
    setError(null);
  }

  const available = (state?.available ?? []).filter(
    (p) => filter === "ALL" || p.position === filter
  );
  const myRoster = (state?.picks ?? []).filter((p) => p.is_user);
  const recentPicks = [...(state?.picks ?? [])].reverse().slice(0, 8);

  // Everything the bots took since your previous pick — so a 13-pick jump reads
  // as "here's what came off the board", not an unexplained skip.
  const sinceYourLastPick = (() => {
    const picks = state?.picks ?? [];
    const myPickNumbers = picks.filter((p) => p.is_user).map((p) => p.overall_pick);
    const lastMine = myPickNumbers.length
      ? myPickNumbers[myPickNumbers.length - 1]
      : 0;
    return picks.filter((p) => p.overall_pick > lastMine && !p.is_user);
  })();

  // Setup screen
  if (loaded && !draftId) {
    return (
      <>
        <Navbar />
        <main className="mx-auto max-w-6xl px-4 py-8">
          <h1 className="text-2xl font-bold">Mock draft</h1>
          <p className="mt-1 text-sm text-gray-500">
            Practice against bots that draft near real consensus ADP — scattered
            by how much actual drafters disagree about each player.
          </p>
          <div className="mt-6 max-w-md rounded-xl border border-gray-200 bg-white p-5">
            <div className="space-y-4">
              <label className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Teams</span>
                <select
                  value={teams}
                  onChange={(e) => {
                    const n = Number(e.target.value);
                    setTeams(n);
                    if (slot > n) setSlot(n);
                  }}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1"
                >
                  {[8, 10, 12, 14, 16].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Rounds</span>
                <select
                  value={rounds}
                  onChange={(e) => setRounds(Number(e.target.value))}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1"
                >
                  {[10, 12, 13, 14, 15, 16, 17, 18, 20].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between text-sm">
                <span className="text-gray-500">Your draft slot</span>
                <select
                  value={slot}
                  onChange={(e) => setSlot(Number(e.target.value))}
                  className="rounded-md border border-gray-300 bg-white px-2 py-1"
                >
                  {Array.from({ length: teams }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button
              onClick={startDraft}
              disabled={busy}
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
            >
              <Play className="h-4 w-4" />
              {busy ? "Setting up…" : "Start mock draft"}
            </button>
            {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Mock draft</h1>
            {state && (
              <p className="mt-1 text-sm text-gray-500">
                {state.teams}-team · {state.rounds} rounds · you&apos;re at slot{" "}
                {state.my_slot} · {state.scoring}
              </p>
            )}
          </div>
          <button
            onClick={reset}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100"
          >
            <RotateCcw className="h-4 w-4" /> New draft
          </button>
        </div>

        {isLoading && <p className="mt-6 text-sm text-gray-400">Loading…</p>}
        {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

        {state && (
          <>
            {/* Status */}
            <div className="mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-gray-200 bg-white p-4">
              <span className="text-sm text-gray-500">
                Round{" "}
                <span className="font-semibold text-gray-900">
                  {state.current_round ?? state.rounds}
                </span>
              </span>
              <span className="text-sm text-gray-500">
                Pick {state.picks_made} / {state.total_picks}
              </span>
              <div className="ml-auto">
                {state.status === "complete" ? (
                  <span className="flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1 text-sm font-semibold text-white">
                    <Trophy className="h-4 w-4" /> Draft complete
                  </span>
                ) : state.is_my_turn ? (
                  <span className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-1 text-sm font-semibold text-white">
                    <Zap className="h-4 w-4" /> You&apos;re on the clock — pick #
                    {state.on_the_clock}
                  </span>
                ) : (
                  <span className="rounded-lg bg-gray-100 px-3 py-1 text-sm text-gray-600">
                    Team {state.current_slot} is picking…
                  </span>
                )}
              </div>
            </div>

            {/* What the bots took while you were away — so the jump to your next
                pick reads as real draft action, not a random skip. */}
            {state.is_my_turn && sinceYourLastPick.length > 0 && (
              <div className="mt-4 rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {sinceYourLastPick.length} taken since your last pick
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {sinceYourLastPick.map((p) => (
                    <span
                      key={p.overall_pick}
                      className="flex items-center gap-1 rounded-md border border-gray-200 px-2 py-1 text-xs"
                    >
                      <span className="text-gray-400">#{p.overall_pick}</span>
                      <span
                        className={`flex h-4 w-4 items-center justify-center rounded text-[8px] font-bold text-white ${positionColor(p.position)}`}
                      >
                        {p.position}
                      </span>
                      <span className="max-w-[9rem] truncate">
                        {p.snapshot?.name ?? p.player_id}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Results */}
            {state.status === "complete" && results && (
              <div className="mt-5 rounded-xl border border-green-200 bg-green-50 p-5">
                <h2 className="text-lg font-bold">
                  You finished {results.your_rank} of {results.teams}
                </h2>
                <p className="mt-1 text-sm text-gray-600">
                  {results.your_total_vor} total value over replacement — league
                  average {results.league_average_vor}.
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {results.best_pick && (
                    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
                      <p className="text-xs font-semibold uppercase text-gray-500">
                        Best value
                      </p>
                      <p className="font-semibold">{results.best_pick.name}</p>
                      <p className="text-xs text-gray-500">
                        {results.best_pick.position} · {results.best_pick.vor} VOR
                        {results.best_pick.adp_delta != null
                          ? ` · went ${results.best_pick.adp_delta} picks late`
                          : ""}
                      </p>
                    </div>
                  )}
                  {results.worst_pick && (
                    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
                      <p className="text-xs font-semibold uppercase text-gray-500">
                        Biggest reach
                      </p>
                      <p className="font-semibold">{results.worst_pick.name}</p>
                      <p className="text-xs text-gray-500">
                        {results.worst_pick.position} · {results.worst_pick.vor} VOR
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="mt-6 grid gap-6 lg:grid-cols-3">
              {/* Available */}
              <div className="lg:col-span-2">
                <div className="flex items-center justify-between">
                  <div className="flex flex-wrap gap-1.5">
                    {POSITIONS.map((p) => (
                      <button
                        key={p}
                        onClick={() => setFilter(p)}
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          filter === p
                            ? "bg-green-600 text-white"
                            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                  <span className="text-xs text-gray-500">
                    {available.length} available
                  </span>
                </div>

                <ul className="mt-3 max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
                  {available.slice(0, 120).map((p) => (
                    <li
                      key={p.player_id}
                      className="flex items-center gap-2.5 rounded-lg border border-gray-200 bg-white p-2.5"
                    >
                      <span
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                      >
                        {p.position}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-1.5 truncate text-sm font-semibold">
                          {p.name}
                        </p>
                        <p className="truncate text-xs text-gray-500">
                          {p.team ?? "FA"}
                          {p.bye_week ? ` · bye ${p.bye_week}` : ""}
                          {p.adp ? ` · ADP ${p.adp}` : ""}
                          {p.vor ? ` · ${p.vor} VOR` : ""}
                        </p>
                      </div>
                      <button
                        onClick={() => pick(p.player_id)}
                        disabled={!state.is_my_turn || busy}
                        className="rounded-md bg-green-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-green-700 disabled:opacity-40"
                      >
                        Draft
                      </button>
                    </li>
                  ))}
                  {available.length === 0 && (
                    <p className="mt-4 text-sm text-gray-400">
                      Nobody left at this position.
                    </p>
                  )}
                </ul>
              </div>

              {/* Side panels */}
              <div className="space-y-4">
                {state.is_my_turn && (state.recommendations ?? []).length > 0 && (
                  <div className="rounded-xl border border-gray-200 bg-white p-5">
                    <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                      Suggested
                    </h2>
                    <ul className="mt-3 space-y-3">
                      {(state.recommendations ?? []).map((r, i) => (
                        <li key={r.player_id} className="text-sm">
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-gray-400">{i + 1}</span>
                            <span
                              className={`flex h-5 w-5 items-center justify-center rounded text-[9px] font-bold text-white ${positionColor(r.position)}`}
                            >
                              {r.position}
                            </span>
                            <span className="flex-1 truncate font-semibold">
                              {r.name}
                            </span>
                            <button
                              onClick={() => pick(r.player_id)}
                              disabled={busy}
                              className="rounded-md bg-green-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-green-700 disabled:opacity-40"
                            >
                              Draft
                            </button>
                          </div>
                          <ul className="mt-1 space-y-0.5 pl-7">
                            {r.reasons.slice(0, 3).map((why) => (
                              <li key={why} className="text-xs text-gray-500">
                                · {why}
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="rounded-xl border border-gray-200 bg-white p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                    Your team ({myRoster.length})
                  </h2>
                  <ul className="mt-3 space-y-1.5">
                    {myRoster.map((p) => (
                      <li
                        key={p.overall_pick}
                        className="flex items-center gap-2 text-sm"
                      >
                        {/* Standard draft notation is round.pick-within-round
                            (2.08), not round.overall-pick (2.20). */}
                        <span className="w-8 text-xs text-gray-400">
                          {p.round}.
                          {String(
                            ((p.overall_pick - 1) % state.teams) + 1
                          ).padStart(2, "0")}
                        </span>
                        <span
                          className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                        >
                          {p.position}
                        </span>
                        <span className="flex-1 truncate font-medium">
                          {p.snapshot?.name ?? p.player_id}
                        </span>
                      </li>
                    ))}
                    {myRoster.length === 0 && (
                      <p className="text-sm text-gray-400">No picks yet.</p>
                    )}
                  </ul>
                </div>

                <div className="rounded-xl border border-gray-200 bg-white p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                    Recent picks
                  </h2>
                  <ul className="mt-3 space-y-1.5">
                    {recentPicks.map((p) => (
                      <li
                        key={p.overall_pick}
                        className={`flex items-center gap-2 text-sm ${p.is_user ? "font-semibold" : ""}`}
                      >
                        <span className="w-10 text-xs text-gray-400">
                          #{p.overall_pick}
                        </span>
                        <span className="w-14 truncate text-xs text-gray-500">
                          {p.is_user ? "You" : `Team ${p.team_slot}`}
                        </span>
                        <span className="flex-1 truncate">
                          {p.snapshot?.name ?? p.player_id}
                        </span>
                      </li>
                    ))}
                    {recentPicks.length === 0 && (
                      <p className="text-sm text-gray-400">Draft hasn&apos;t started.</p>
                    )}
                  </ul>
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}
