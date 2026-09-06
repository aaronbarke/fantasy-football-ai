"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { EmptyState, ErrorState } from "@/components/PageState";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { injuryColor, positionColor, timeAgo } from "@/lib/utils";
import {
  RotateCcw,
  Sparkles,
  TrendingUp,
  Newspaper,
  Radio,
  Play,
  AlertTriangle,
} from "lucide-react";
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

interface LivePick {
  overall_pick: number;
  round: number;
  team_id: string;
  player_id: string | null;
  is_you: boolean;
  made: boolean;
}

interface LiveDraft {
  status:
    "not_started" | "in_progress" | "complete" | "unavailable" | "auth_expired";
  total_picks: number;
  picks_made: number;
  your_team_id: string | null;
  your_slot: number | null;
  on_the_clock: { overall_pick: number; is_you: boolean } | null;
  drafted_player_ids: string[];
  your_player_ids: string[];
  unmapped_count: number;
  picks: LivePick[];
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
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) *
      t +
      0.254829592) *
      t *
      Math.exp(-ax * ax);
  return sign * y;
}

function availabilityAt(
  adp: number | null,
  stdev: number | null,
  pick: number | null,
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
      title={`Sharp drafters take him ~${Math.round(edge)} picks earlier than ESPN, so he falls to you if your league drafts off ESPN`}
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

/** Shown when ESPN rejects our stored cookies (401/403). Mid-draft this is the
 * one failure that needs the user to act — the fix (reconnect with fresh
 * espn_s2/SWID) lives on /connect, so link straight there. */
function CookieExpiredBanner() {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-3 rounded-xl border border-red-300 bg-red-50 p-4 dark:border-red-500/40 dark:bg-red-500/10">
      <AlertTriangle className="h-5 w-5 shrink-0 text-red-600 dark:text-red-400" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-red-800 dark:text-red-300">
          ESPN rejected your login. Your cookies have expired
        </p>
        <p className="mt-0.5 text-xs text-red-700 dark:text-red-400">
          Live sync can&apos;t read your draft until you reconnect with fresh
          espn_s2 and SWID cookies. Picks won&apos;t auto-mark until then, but
          you can keep drafting with the manual “My pick / Gone” buttons in the
          meantime.
        </p>
      </div>
      <Link
        href="/connect"
        className="shrink-0 rounded-lg bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-700"
      >
        Reconnect league
      </Link>
    </div>
  );
}

export default function DraftPage() {
  const { league } = useLeague({ requireLeague: false });
  const [manualDrafted, setManualDrafted] = useState<Record<string, DraftMark>>(
    {},
  );
  const [filter, setFilter] = useState("ALL");
  const [teams, setTeams] = useState(12);
  const [slot, setSlot] = useState(1);
  const [advice, setAdvice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [liveSync, setLiveSync] = useState(false);
  const [demoPicks, setDemoPicks] = useState(0); // 0 = off; >0 = preview in progress
  const [externalId, setExternalId] = useState(""); // ESPN league ID for external sync
  const [externalInput, setExternalInput] = useState(""); // controlled input
  const externalSync = externalId.length > 0;

  useEffect(() => {
    try {
      const savedState = localStorage.getItem(STATE_KEY);
      if (savedState) setManualDrafted(JSON.parse(savedState));
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
    if (loaded)
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ teams, slot }));
  }, [teams, slot, loaded]);

  function mark(id: string, value: DraftMark | null) {
    setManualDrafted((d) => {
      const next = { ...d };
      if (value === null) delete next[id];
      else next[id] = value;
      localStorage.setItem(STATE_KEY, JSON.stringify(next));
      return next;
    });
  }

  const isEspn = league?.platform === "espn";
  const demoMode = demoPicks > 0;
  // Whenever the board is driven externally — real ESPN sync, preview, or external ID sync.
  const liveActive = liveSync || demoMode || externalSync;

  // Poll the real ESPN draft while live sync is on (or replay the synthetic
  // preview). Its picks become the source of truth for what's off the board.
  const { data: liveConn } = useQuery({
    queryKey: ["liveDraft", league?.id, demoMode ? demoPicks : "real"],
    queryFn: () =>
      api<LiveDraft>(
        `/api/draft/live?connection_id=${league!.id}` +
          (demoMode ? `&demo_picks=${demoPicks}` : ""),
      ),
    enabled:
      !externalSync && liveActive && !!league?.id && (isEspn || demoMode),
    refetchInterval: demoMode ? false : 6000,
  });

  // External sync — poll any ESPN draft by raw league ID (mock lobby, etc.)
  const { data: liveExt } = useQuery({
    queryKey: ["liveDraftExternal", externalId],
    queryFn: () =>
      api<LiveDraft>(`/api/draft/live-external?espn_league_id=${externalId}`),
    enabled: externalSync,
    refetchInterval: 6000,
  });

  const live = externalSync ? liveExt : liveConn;

  // Advance the preview a couple of picks at a time so the room plays out.
  useEffect(() => {
    if (!demoMode) return;
    const cap = live?.total_picks ?? 240;
    if (demoPicks >= cap) return;
    const t = setTimeout(() => setDemoPicks((p) => Math.min(p + 2, cap)), 1400);
    return () => clearTimeout(t);
  }, [demoMode, demoPicks, live?.total_picks]);

  // When live, the feed drives the board: your picks are "me", everyone
  // else's are "gone". Otherwise fall back to manual tracking.
  const drafted = useMemo<Record<string, DraftMark>>(() => {
    if (liveActive && live) {
      const map: Record<string, DraftMark> = {};
      for (const id of live.drafted_player_ids) map[id] = "gone";
      for (const id of live.your_player_ids) map[id] = "me";
      return map;
    }
    return manualDrafted;
  }, [liveActive, live, manualDrafted]);

  const {
    data,
    isLoading,
    error: boardError,
    refetch: reloadBoard,
  } = useQuery({
    queryKey: ["draftBoard", league?.id],
    queryFn: () =>
      api<BoardResponse>(
        `/api/draft/board?limit=450${league ? `&connection_id=${league.id}` : ""}`,
      ),
    staleTime: 30 * 60_000,
  });

  // In live mode the league is the source of truth: adopt its team count (so
  // snake-pick math is right) and your real draft slot from the feed.
  useEffect(() => {
    if (liveActive && data?.league_size && data.league_size !== teams) {
      setTeams(data.league_size);
    }
  }, [liveActive, data?.league_size, teams]);

  useEffect(() => {
    if (liveActive && live?.your_slot && live.your_slot !== slot) {
      setSlot(live.your_slot);
    }
  }, [liveActive, live?.your_slot, slot]);

  const board = useMemo(() => data?.players ?? [], [data]);
  // Name/position lookup for the feed and your-roster panel. Includes the
  // late-round K/DEF pool (they live on a separate board), so a drafted kicker
  // or defense resolves to a name instead of reading "(unmatched pick)".
  const nameById = useMemo(() => {
    const m: Record<
      string,
      Pick<BoardPlayer, "player_id" | "name" | "position" | "team" | "bye_week">
    > = {};
    for (const p of board) m[p.player_id] = p;
    for (const p of data?.late_round ?? []) m[p.player_id] = p;
    return m;
  }, [board, data]);
  const myIds = useMemo(
    () => Object.keys(drafted).filter((id) => drafted[id] === "me"),
    [drafted],
  );
  const totalPicked = Object.keys(drafted).length;

  // Most recent completed picks from the live feed, newest first, with names
  // resolved off the board so we can show "Team 7 took CeeDee Lamb".
  const livePickFeed = useMemo(() => {
    if (!liveActive || !live) return [];
    return live.picks
      .filter((p) => p.made)
      .slice(-12)
      .reverse()
      .map((p) => ({
        ...p,
        player: p.player_id ? nameById[p.player_id] : undefined,
      }));
  }, [liveActive, live, nameById]);

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
  const filtered = useMemo(
    () => available.filter((p) => filter === "ALL" || p.position === filter),
    [available, filter],
  );
  // When live/preview, each of your picks carries the round it was made in — so
  // the roster can read in true draft order instead of a jumble.
  const myPickRound = useMemo(() => {
    const m: Record<string, { round: number; overall: number }> = {};
    if (liveActive && live) {
      for (const p of live.picks) {
        if (p.is_you && p.made && p.player_id) {
          m[p.player_id] = { round: p.round, overall: p.overall_pick };
        }
      }
    }
    return m;
  }, [liveActive, live]);

  // Your roster — resolved through nameById so drafted K/DEF (not on the main
  // board) still appear alongside your offense picks. Sorted into draft order
  // when we know it, so "which round did I take him" is obvious at a glance.
  const myPlayers = useMemo(() => {
    const cards = Object.keys(drafted)
      .filter((id) => drafted[id] === "me")
      .map((id) => nameById[id])
      .filter(Boolean);
    if (Object.keys(myPickRound).length) {
      return [...cards].sort(
        (a, b) =>
          (myPickRound[a.player_id]?.overall ?? 1e9) -
          (myPickRound[b.player_id]?.overall ?? 1e9),
      );
    }
    return cards;
  }, [drafted, nameById, myPickRound]);

  const { data: rec, isFetching: recLoading } = useQuery({
    queryKey: [
      "draftRecommend",
      league?.id,
      myIds.join(","),
      totalPicked,
      teams,
      slot,
    ],
    queryFn: () =>
      api<RecommendResponse>("/api/draft/recommend", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league?.id ?? null,
          my_player_ids: myIds,
          drafted_ids: Object.keys(drafted).filter(
            (id) => drafted[id] === "gone",
          ),
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
          drafted_ids: Object.keys(drafted).filter(
            (id) => drafted[id] === "gone",
          ),
          next_pick: nextPick,
          following_pick: followingPick,
        }),
      });
      setAdvice(resp.analysis);
    } catch (err) {
      setAdvice(
        `Something went wrong: ${err instanceof Error ? err.message : "unknown"}`,
      );
    } finally {
      setBusy(false);
    }
  }

  const needs = rec?.needs ?? {};

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
            <p className="eyebrow">Make every pick count</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Your draft room.
            </h1>
            <p className="page-description">
              Find your next pick. Track who’s available, compare value, and
              build your roster.
            </p>
            <p className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-green-700">
              {(data?.scoring ?? "ppr").replace("_", "-")} ·{" "}
              {data?.league_size ?? teams} teams
            </p>
          </div>
          <button
            onClick={() => {
              localStorage.removeItem(STATE_KEY);
              setManualDrafted({});
              setAdvice(null);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100"
          >
            <RotateCcw className="h-4 w-4" /> Reset draft
          </button>
        </div>

        {/* Live sync (ESPN) + draft-day preview */}
        {league && (
          <div
            className={`mt-5 flex flex-wrap items-center gap-3 rounded-xl border p-4 ${
              liveActive
                ? "border-green-300 bg-green-50 dark:border-green-500/40"
                : "border-gray-200 bg-white"
            }`}
          >
            {isEspn && !externalSync && (
              <button
                onClick={() => {
                  setDemoPicks(0);
                  setLiveSync((v) => !v);
                }}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-semibold ${
                  liveSync
                    ? "bg-green-600 text-white hover:bg-green-700"
                    : "border border-gray-300 hover:bg-gray-100"
                }`}
              >
                <Radio className="h-4 w-4" />
                {liveSync ? "Live sync on" : "Sync my ESPN draft"}
              </button>
            )}
            {!liveSync && !externalSync && (
              <button
                onClick={() => setDemoPicks((p) => (p > 0 ? 0 : 1))}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-semibold ${
                  demoMode
                    ? "bg-green-600 text-white hover:bg-green-700"
                    : "border border-gray-300 hover:bg-gray-100"
                }`}
              >
                <Play className="h-4 w-4" />
                {demoMode ? "Stop preview" : "Preview draft day"}
              </button>
            )}
            {liveSync && live && (
              <span className="text-sm text-gray-600">
                {live.status === "not_started" &&
                  "Draft hasn't started. Picks will appear here as they happen."}
                {live.status === "in_progress" &&
                  `Live · ${live.picks_made}/${live.total_picks} picked` +
                    (live.on_the_clock
                      ? live.on_the_clock.is_you
                        ? " · you're on the clock"
                        : ` · pick #${live.on_the_clock.overall_pick} on the clock`
                      : "")}
                {live.status === "complete" && "Draft complete."}
                {live.status === "unavailable" &&
                  "Couldn't reach the ESPN draft. Check that your league is synced."}
              </span>
            )}
            {demoMode && live && (
              <span className="text-sm text-gray-600">
                Preview · {live.picks_made}/{live.total_picks} picked
                {live.on_the_clock?.is_you ? " · you're on the clock" : ""}.
                This is a dry run, not your real draft.
              </span>
            )}
            {liveSync && (live?.unmapped_count ?? 0) > 0 && (
              <span className="text-xs text-amber-600">
                {live!.unmapped_count} pick(s) not matched to our player pool
              </span>
            )}
          </div>
        )}

        {/* Expired-cookie banner — applies to either sync path (live is the
            merged connected/external state). This is the one mid-draft failure
            the user has to act on, so it gets a loud banner, not an inline note. */}
        {liveActive && live?.status === "auth_expired" && (
          <CookieExpiredBanner />
        )}

        {/* External ESPN sync — paste any ESPN league ID to follow that draft */}
        <div
          className={`mt-5 rounded-xl border p-4 ${
            externalSync
              ? "border-indigo-300 bg-indigo-50 dark:border-indigo-500/40 dark:bg-indigo-500/5"
              : "border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800"
          }`}
        >
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">
              Sync any ESPN draft
            </span>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const raw = externalInput.trim();
                const idMatch = raw.match(/leagueId=(\d+)/);
                setExternalId(idMatch ? idMatch[1] : raw);
              }}
              className="flex items-center gap-2"
            >
              <input
                type="text"
                placeholder="ESPN league ID or URL"
                value={externalInput}
                onChange={(e) => setExternalInput(e.target.value)}
                disabled={externalSync}
                className="w-56 rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-sm placeholder:text-gray-400 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              />
              {!externalSync ? (
                <button
                  type="submit"
                  disabled={!externalInput.trim()}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  Sync
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setExternalId("");
                    setExternalInput("");
                  }}
                  className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-semibold hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-700"
                >
                  Disconnect
                </button>
              )}
            </form>
            {externalSync && liveExt && (
              <span className="text-sm text-gray-600 dark:text-gray-300">
                {liveExt.status === "not_started" &&
                  "Draft hasn't started yet. Watching for picks."}
                {liveExt.status === "in_progress" &&
                  `Live · ${liveExt.picks_made}/${liveExt.total_picks} picked` +
                    (liveExt.on_the_clock
                      ? ` · pick #${liveExt.on_the_clock.overall_pick} on the clock`
                      : "")}
                {liveExt.status === "complete" && "Draft complete."}
                {liveExt.status === "unavailable" &&
                  "Couldn't reach that ESPN draft. Check the league ID."}
              </span>
            )}
            {externalSync && (liveExt?.unmapped_count ?? 0) > 0 && (
              <span className="text-xs text-amber-600">
                {liveExt!.unmapped_count} pick(s) not matched to our player pool
              </span>
            )}
          </div>
          {!externalSync && (
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
              Paste the league ID from any ESPN draft URL (or the full URL).
              Works with the ESPN Mock Draft Lobby: join a lobby mock, copy the
              league ID from the URL bar, and paste it here to watch picks sync
              live.
            </p>
          )}
        </div>

        {/* Draft position */}
        <div className="mt-5 flex flex-wrap items-center gap-4 rounded-xl border border-gray-200 bg-white p-4">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Teams</span>
            <select
              value={teams}
              onChange={(e) => setTeams(Number(e.target.value))}
              disabled={liveActive}
              className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm disabled:opacity-50"
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
              disabled={liveActive}
              className="rounded-md border border-gray-300 bg-white px-2 py-1 text-sm disabled:opacity-50"
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
            <span className="text-gray-500">{totalPicked} off the board</span>
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
          <div className="min-w-0 lg:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
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
            {boardError && (
              <ErrorState
                message="The draft board couldn’t load."
                retry={() => void reloadBoard()}
              />
            )}
            {!isLoading && !boardError && board.length === 0 && (
              <EmptyState
                title="Your board is warming up"
                description="Rankings will appear when this season’s draft data is available. Check back before your draft."
              />
            )}

            <ul className="mt-3 max-h-[65vh] space-y-1.5 overflow-y-auto pr-1">
              {filtered.slice(0, 150).map((p, i) => {
                const prev = filtered[i - 1];
                const tierBreak =
                  prev &&
                  (prev.position !== p.position || prev.tier !== p.tier);
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
                      className={`flex flex-wrap items-center gap-2.5 rounded-lg border bg-white p-2.5 ${
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
                      <div className="min-w-0 w-[calc(100%-80px)] sm:w-auto sm:flex-1">
                        <p className="flex flex-wrap items-center gap-1.5 text-sm font-semibold">
                          {p.name}
                          <TierBadge tier={p.tier} />
                          <ValueBadge
                            score={p.value_score}
                            delta={p.adp_delta}
                          />
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
                              title="No NFL team, so the projection is market-implied only"
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
                              title={`${news[0].headline} · ${timeAgo(news[0].published_at)}`}
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
                      {/* Live sync drives the board from the real draft, so the
                          manual pick controls step aside. */}
                      {!liveActive && (
                        <>
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
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Recommendations + roster */}
          <div className="min-w-0 space-y-4">
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
                      {!liveActive && (
                        <button
                          onClick={() => mark(r.player_id, "me")}
                          className="rounded-md bg-green-600 px-2 py-0.5 text-[11px] font-semibold text-white hover:bg-green-700"
                        >
                          Take
                        </button>
                      )}
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

            {/* Live draft feed — what just came off the board in the real draft */}
            {liveActive && livePickFeed.length > 0 && (
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                  Draft feed
                </h2>
                <ul className="mt-3 space-y-1.5">
                  {livePickFeed.map((p) => (
                    <li
                      key={p.overall_pick}
                      className={`flex items-center gap-2 text-sm ${p.is_you ? "font-semibold" : ""}`}
                    >
                      <span className="w-10 shrink-0 text-xs text-gray-400">
                        {p.round}.
                        {String(((p.overall_pick - 1) % teams) + 1).padStart(
                          2,
                          "0",
                        )}
                      </span>
                      {p.player && (
                        <span
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-[9px] font-bold text-white ${positionColor(p.player.position)}`}
                        >
                          {p.player.position}
                        </span>
                      )}
                      <span className="flex-1 truncate">
                        {p.player?.name ??
                          (p.player_id ? "(unmatched pick)" : "—")}
                      </span>
                      <span className="shrink-0 text-xs text-gray-400">
                        {p.is_you ? "You" : `Tm ${p.team_id}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

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
                  <li
                    key={p.player_id}
                    className="flex items-center gap-2 text-sm"
                  >
                    {myPickRound[p.player_id] && (
                      <span className="w-7 shrink-0 text-[10px] font-semibold text-gray-400">
                        R{myPickRound[p.player_id].round}
                      </span>
                    )}
                    <span
                      className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                    >
                      {p.position}
                    </span>
                    <span className="flex-1 truncate font-medium">
                      {p.name}
                    </span>
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
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {advice}
                </ReactMarkdown>
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
