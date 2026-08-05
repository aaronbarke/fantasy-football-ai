"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { injuryColor, positionColor, timeAgo } from "@/lib/utils";
import { RotateCcw, Sparkles, TrendingUp, Newspaper } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface BoardPlayer {
  player_id: string;
  name: string;
  position: string;
  team: string | null;
  injury_status: string | null;
  roster_status: string | null;
  bye_week: number | null;
  proj_points: number;
  proj_source: string;
  vor: number;
  tier: number;
  position_rank: number;
  overall_rank: number;
  adp: number | null;
  adp_rank: number | null;
  adp_delta: number | null;
  adp_stdev: number | null;
  market_edge: number | null;
  value_score: number;
  is_tier_end: boolean;
  auction_value: number | null;
}

interface NewsItem {
  headline: string;
  url: string;
  source: string | null;
  published_at: string | null;
}

interface BoardResponse {
  season: number;
  scoring: string;
  league_size: number;
  count: number;
  players: BoardPlayer[];
  late_round: {
    player_id: string;
    name: string;
    position: string;
    team: string | null;
    bye_week: number | null;
    adp: number | null;
  }[];
  news: Record<string, NewsItem[]>;
}

interface Recommendation extends BoardPlayer {
  score: number;
  reasons: string[];
  available_at_following_pick: number | null;
}

interface RecommendResponse {
  needs: Record<string, { required: number; have: number; unfilled: number }>;
  recommendations: Recommendation[];
}

type DraftMark = "me" | "gone";
const POSITIONS = ["ALL", "QB", "RB", "WR", "TE"];
const STATE_KEY = "draft_room_state";
const SETTINGS_KEY = "draft_room_settings";

/** Normal CDF via the Abramowitz-Stegun erf approximation — mirrors
 * `availability_at` in draft_service.py. Duplicated deliberately: recomputing
 * this client-side keeps the (cached, 300-row) board static as picks come off,
 * instead of refetching the whole thing on every single pick. The server stays
 * authoritative for the actual recommendations. */
function erf(x: number): number {
  const sign = x >= 0 ? 1 : -1;
  const ax = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * ax);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-ax * ax);
  return sign * y;
}

function availabilityAt(
  adp: number | null,
  stdev: number | null,
  pick: number | null
): number | null {
  if (adp == null || pick == null) return null;
  if (!stdev || stdev <= 0) return adp > pick ? 1 : 0;
  const z = (pick - adp) / stdev;
  return Math.max(0, Math.min(1, 1 - 0.5 * (1 + erf(z / Math.SQRT2))));
}

/** Overall pick numbers for one seat in a snake draft. */
function myPickNumbers(teams: number, slot: number, rounds = 16): number[] {
  const picks: number[] = [];
  for (let r = 1; r <= rounds; r++) {
    const inRound = r % 2 === 1 ? slot : teams - slot + 1;
    picks.push((r - 1) * teams + inRound);
  }
  return picks;
}

function TierBadge({ tier }: { tier: number }) {
  return (
    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-bold text-gray-600">
      T{tier}
    </span>
  );
}

function ValueBadge({ score, delta }: { score: number; delta: number | null }) {
  if (score < 10 || delta == null) return null;
  return (
    <span
      title={`Market drafts him ${delta} picks later than we rank him`}
      className="flex items-center gap-0.5 rounded bg-green-100 px-1.5 py-0.5 text-[10px] font-bold text-green-700 dark:bg-green-500/15 dark:text-green-300"
    >
      <TrendingUp className="h-3 w-3" />+{delta}
    </span>
  );
}

function EspnEdgeBadge({ edge }: { edge: number | null }) {
  // Positive edge = ESPN drafts him later than sharp mock-drafters, so he falls
  // to you in an ESPN league. Only worth flagging when the gap is real.
  if (edge == null || edge < 18) return null;
  return (
    <span
      title={`Sharp drafters take him ~${Math.round(edge)} picks earlier than ESPN — falls to you if your league drafts off ESPN`}
      className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-bold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
    >
      ESPN value +{Math.round(edge)}
    </span>
  );
}

function AvailabilityPill({ pct }: { pct: number }) {
  const tone =
    pct >= 70
      ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300"
      : pct >= 25
        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
        : "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300";
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${tone}`}
      title="Chance he's still available at your next pick"
    >
      {pct}%
    </span>
  );
}

export default function DraftPage() {
  const { league } = useLeague({ requireLeague: false });
  const [drafted, setDrafted] = useState<Record<string, DraftMark>>({});
  const [filter, setFilter] = useState("ALL");
  const [teams, setTeams] = useState(12);
  const [slot, setSlot] = useState(1);
  const [advice, setAdvice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const savedState = localStorage.getItem(STATE_KEY);
      if (savedState) setDrafted(JSON.parse(savedState));
      const savedSettings = localStorage.getItem(SETTINGS_KEY);
      if (savedSettings) {
        const s = JSON.parse(savedSettings);
        if (s.teams) setTeams(s.teams);
        if (s.slot) setSlot(s.slot);
      }
    } catch {
      /* corrupt state — start fresh */
    }
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (loaded) localStorage.setItem(SETTINGS_KEY, JSON.stringify({ teams, slot }));
  }, [teams, slot, loaded]);

  function mark(id: string, value: DraftMark | null) {
    setDrafted((d) => {
      const next = { ...d };
      if (value === null) delete next[id];
      else next[id] = value;
      localStorage.setItem(STATE_KEY, JSON.stringify(next));
      return next;
    });
  }

  const { data, isLoading } = useQuery({
    queryKey: ["draftBoard", league?.id],
    queryFn: () =>
      api<BoardResponse>(
        `/api/draft/board?limit=300${league ? `&connection_id=${league.id}` : ""}`
      ),
    staleTime: 30 * 60_000,
  });

  const board = useMemo(() => data?.players ?? [], [data]);
  const myIds = useMemo(
    () => Object.keys(drafted).filter((id) => drafted[id] === "me"),
    [drafted]
  );
  const totalPicked = Object.keys(drafted).length;

  // Where you sit right now, and when you're back on the clock
  const { nextPick, followingPick, round } = useMemo(() => {
    const picks = myPickNumbers(teams, slot);
    const current = totalPicked + 1;
    const upcoming = picks.filter((p) => p >= current);
    return {
      nextPick: upcoming[0] ?? null,
      followingPick: upcoming[1] ?? null,
      round: Math.floor(totalPicked / teams) + 1,
    };
  }, [teams, slot, totalPicked]);

  const available = board.filter((p) => !drafted[p.player_id]);
  const filtered = available.filter(
    (p) => filter === "ALL" || p.position === filter
  );
  const myPlayers = board.filter((p) => drafted[p.player_id] === "me");

  const { data: rec, isFetching: recLoading } = useQuery({
    queryKey: ["draftRecommend", league?.id, myIds.join(","), totalPicked, teams, slot],
    queryFn: () =>
      api<RecommendResponse>("/api/draft/recommend", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league?.id ?? null,
          my_player_ids: myIds,
          drafted_ids: Object.keys(drafted).filter((id) => drafted[id] === "gone"),
          next_pick: nextPick,
          following_pick: followingPick,
          limit: 4,
        }),
      }),
    enabled: board.length > 0,
    staleTime: 60_000,
  });

  async function askAI() {
    setBusy(true);
    setAdvice(null);
    try {
      const resp = await api<{ analysis: string }>("/api/draft/advice", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league?.id ?? null,
          my_player_ids: myIds,
          drafted_ids: Object.keys(drafted).filter((id) => drafted[id] === "gone"),
          next_pick: nextPick,
          following_pick: followingPick,
        }),
      });
      setAdvice(resp.analysis);
    } catch (err) {
      setAdvice(
        `Something went wrong: ${err instanceof Error ? err.message : "unknown"}`
      );
    } finally {
      setBusy(false);
    }
  }

  const needs = rec?.needs ?? {};

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Draft room</h1>
            <p className="mt-1 text-sm text-gray-500">
              Consensus ADP from ESPN and real mock drafts, our own season
              projections, and value over replacement — {data?.scoring ?? "ppr"}{" "}
              scoring, {data?.league_size ?? teams}-team.
            </p>
          </div>
          <button
            onClick={() => {
              localStorage.removeItem(STATE_KEY);
              setDrafted({});
              setAdvice(null);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100"
          >
            <RotateCcw className="h-4 w-4" /> Reset draft
          </button>
        </div>

        {/* Draft position */}
        <div className="mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-gray-200 bg-white p-4">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Teams</span>
            <select
              value={teams}
              onChange={(e) => setTeams(Number(e.target.value))}
              className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm"
            >
              {[8, 10, 12, 14, 16].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Your slot</span>
            <select
              value={slot}
              onChange={(e) => setSlot(Number(e.target.value))}
              className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm"
            >
              {Array.from({ length: teams }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div className="ml-auto flex items-center gap-4 text-sm">
            <span className="text-gray-500">
              Round <span className="font-semibold text-gray-900">{round}</span>
            </span>
            <span className="text-gray-500">
              {totalPicked} off the board
            </span>
            {nextPick && (
              <span className="rounded-lg bg-green-600 px-3 py-1 font-semibold text-white">
                You pick #{nextPick}
                {followingPick ? ` · then #${followingPick}` : ""}
              </span>
            )}
          </div>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          {/* Board */}
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
                    {p !== "ALL" && needs[p] && (
                      <span className="ml-1 opacity-70">
                        {needs[p].have}/{needs[p].required}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <span className="text-xs text-gray-500">
                {filtered.length} available
              </span>
            </div>

            {isLoading && (
              <p className="mt-6 text-sm text-gray-400">Loading the board…</p>
            )}
            {!isLoading && board.length === 0 && (
              <p className="mt-6 text-sm text-gray-400">
                No draft data yet — run the draft-data sync to pull ADP and
                projections.
              </p>
            )}

            <ul className="mt-3 max-h-[65vh] space-y-1.5 overflow-y-auto pr-1">
              {filtered.slice(0, 150).map((p, i) => {
                const prev = filtered[i - 1];
                const tierBreak =
                  prev && (prev.position !== p.position || prev.tier !== p.tier);
                const avail = availabilityAt(p.adp, p.adp_stdev, followingPick);
                const news = data?.news?.[p.player_id];
                return (
                  <li key={p.player_id}>
                    {tierBreak && filter !== "ALL" && (
                      <div className="my-2 flex items-center gap-2">
                        <div className="h-px flex-1 bg-gray-200" />
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
                          Tier {p.tier}
                        </span>
                        <div className="h-px flex-1 bg-gray-200" />
                      </div>
                    )}
                    <div
                      className={`flex items-center gap-2.5 rounded-lg border bg-white p-2.5 ${
                        p.is_tier_end
                          ? "border-amber-300 dark:border-amber-500/40"
                          : "border-gray-200"
                      }`}
                    >
                      <span className="w-6 text-right text-xs text-gray-400">
                        {p.overall_rank}
                      </span>
                      <span
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                      >
                        {p.position}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-1.5 truncate text-sm font-semibold">
                          {p.name}
                          <TierBadge tier={p.tier} />
                          <ValueBadge score={p.value_score} delta={p.adp_delta} />
                          <EspnEdgeBadge edge={p.market_edge} />
                          {p.injury_status && (
                            <span
                              className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${injuryColor(p.injury_status)}`}
                            >
                              {p.injury_status}
                            </span>
                          )}
                          {p.roster_status === "free_agent" && (
                            <span
                              title="No NFL team — projection is market-implied only"
                              className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-bold text-gray-600 dark:bg-gray-500/20 dark:text-gray-300"
                            >
                              FA
                            </span>
                          )}
                          {news && news.length > 0 && (
                            <a
                              href={news[0].url}
                              target="_blank"
                              rel="noreferrer"
                              title={`${news[0].headline} — ${timeAgo(news[0].published_at)}`}
                              className="text-gray-400 hover:text-green-600"
                            >
                              <Newspaper className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </p>
                        <p className="truncate text-xs text-gray-500">
                          {p.team ?? "FA"}
                          {p.bye_week ? ` · bye ${p.bye_week}` : ""} ·{" "}
                          {p.proj_points} proj ·{" "}
                          <span className="font-semibold text-green-700 dark:text-green-400">
                            {p.vor} VOR
                          </span>
                          {p.adp ? ` · ADP ${p.adp}` : ""}
                          {p.is_tier_end ? " · last of tier" : ""}
                        </p>
                      </div>
                      {/* Only worth showing where it's a live question. At the
                          top of the board everyone reads 0%, which is just noise. */}
                      {avail != null && followingPick && avail > 0.02 && (
                        <AvailabilityPill pct={Math.round(avail * 100)} />
                      )}
                      <button
                        onClick={() => mark(p.player_id, "me")}
                        className="rounded-md bg-green-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-green-700"
                      >
                        My pick
                      </button>
                      <button
                        onClick={() => mark(p.player_id, "gone")}
                        className="rounded-md border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
                      >
                        Gone
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Recommendations + roster */}
          <div className="space-y-4">
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                Best available{nextPick ? ` at #${nextPick}` : ""}
              </h2>
              {recLoading && (
                <p className="mt-3 text-sm text-gray-400">Thinking…</p>
              )}
              <ul className="mt-3 space-y-3">
                {(rec?.recommendations ?? []).map((r, i) => (
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
                        onClick={() => mark(r.player_id, "me")}
                        className="rounded-md bg-green-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-green-700"
                      >
                        Take
                      </button>
                    </div>
                    <ul className="mt-1 space-y-0.5 pl-7">
                      {r.reasons.map((why) => (
                        <li key={why} className="text-xs text-gray-500">
                          · {why}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
                {!recLoading && (rec?.recommendations ?? []).length === 0 && (
                  <p className="text-sm text-gray-400">No suggestions yet.</p>
                )}
              </ul>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                Your roster ({myPlayers.length})
              </h2>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(needs).map(([pos, n]) => (
                  <span
                    key={pos}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                      n.unfilled > 0
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
                        : "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300"
                    }`}
                  >
                    {pos} {n.have}/{n.required}
                  </span>
                ))}
              </div>
              <ul className="mt-3 space-y-1.5">
                {myPlayers.map((p) => (
                  <li key={p.player_id} className="flex items-center gap-2 text-sm">
                    <span
                      className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                    >
                      {p.position}
                    </span>
                    <span className="flex-1 truncate font-medium">{p.name}</span>
                    <span className="text-xs text-gray-400">
                      {p.bye_week ? `bye ${p.bye_week}` : ""}
                    </span>
                    <button
                      onClick={() => mark(p.player_id, null)}
                      className="text-xs text-gray-400 hover:text-red-500"
                    >
                      undo
                    </button>
                  </li>
                ))}
                {myPlayers.length === 0 && (
                  <p className="text-sm text-gray-400">No picks yet.</p>
                )}
              </ul>
            </div>

            <button
              onClick={askAI}
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-green-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" />
              {busy ? "Thinking…" : "Who should I take?"}
            </button>

            {advice && (
              <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-sm leading-relaxed">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{advice}</ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
