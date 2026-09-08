"use client";

import { useState } from "react";
import Navbar from "@/components/Navbar";
import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import type { PlayerCard } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import {
  ArrowLeftRight,
  Search,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function PlayerSearchAdd({
  onAdd,
  exclude,
}: {
  onAdd: (p: PlayerCard) => void;
  exclude: string[];
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlayerCard[]>([]);

  async function search(value: string) {
    setQ(value);
    if (value.length < 2) {
      setResults([]);
      return;
    }
    try {
      const found = await api<
        {
          id: string;
          full_name: string;
          position: string | null;
          team: string | null;
        }[]
      >(`/api/players/search?q=${encodeURIComponent(value)}`);
      setResults(
        found
          .filter((p) => !exclude.includes(p.id))
          .slice(0, 6)
          .map((p) => ({
            id: p.id,
            name: p.full_name,
            position: p.position,
            team: p.team,
          })),
      );
    } catch {
      setResults([]);
    }
  }

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2">
        <Search className="h-4 w-4 text-gray-400" />
        <input
          value={q}
          onChange={(e) => search(e.target.value)}
          placeholder="Add player…"
          className="w-full border-0 bg-transparent text-sm focus:outline-none"
        />
      </div>
      {results.length > 0 && (
        <div className="absolute left-0 top-full z-20 mt-1 w-full rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          {results.map((p) => (
            <button
              key={p.id}
              onClick={() => {
                onAdd(p);
                setQ("");
                setResults([]);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50"
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
              >
                {p.position}
              </span>
              {p.name} <span className="text-xs text-gray-400">{p.team}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function TradeSide({
  title,
  players,
  setPlayers,
  excludeIds,
}: {
  title: string;
  players: PlayerCard[];
  setPlayers: (p: PlayerCard[]) => void;
  excludeIds: string[];
}) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </h2>
      <div className="mt-3 space-y-2">
        {players.map((p) => (
          <div
            key={p.id}
            className="flex items-center gap-3 rounded-lg border border-gray-200 p-2.5"
          >
            <span
              className={`flex h-8 w-8 items-center justify-center rounded text-xs font-bold text-white ${positionColor(p.position)}`}
            >
              {p.position}
            </span>
            <div className="flex-1">
              <p className="text-sm font-semibold">{p.name}</p>
              <p className="text-xs text-gray-500">{p.team}</p>
            </div>
            <button
              onClick={() => setPlayers(players.filter((x) => x.id !== p.id))}
              className="rounded p-1 hover:bg-gray-100"
              aria-label={`Remove ${p.name}`}
            >
              <X className="h-4 w-4 text-gray-400" />
            </button>
          </div>
        ))}
        {players.length < 6 && (
          <PlayerSearchAdd
            onAdd={(p) => setPlayers([...players, p])}
            exclude={excludeIds}
          />
        )}
      </div>
    </section>
  );
}

interface TradePlayerValue {
  id: string;
  name: string;
  value: number;
  ppg: number | null;
  trend?: string | null;
}

function TrendArrow({ trend }: { trend?: string | null }) {
  if (trend === "rising")
    return (
      <TrendingUp
        className="inline h-3 w-3 text-green-500"
        aria-label="rising"
      />
    );
  if (trend === "falling")
    return (
      <TrendingDown
        className="inline h-3 w-3 text-red-500"
        aria-label="falling"
      />
    );
  return null;
}

interface TradeResult {
  analysis: string;
  give_value: number;
  receive_value: number;
  verdict: string;
  player_values: TradePlayerValue[];
  sweeteners: TradePlayerValue[];
}

type FinderPlayer = {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  value: number | null;
  ppg: number | null;
  trend: string | null;
};

type FinderTrade = {
  partner: { team_id: string; owner_name: string; record: string };
  give: FinderPlayer;
  receive: FinderPlayer;
  value_gap: number;
  your_lineup_gain: number;
  their_lineup_gain: number;
  rationale: string;
};

function finderPlayerCard(p: FinderPlayer): PlayerCard {
  return { id: p.id, name: p.name, position: p.position, team: p.team };
}

export default function TradePage() {
  const { league } = useLeague();
  const [give, setGive] = useState<PlayerCard[]>([]);
  const [receive, setReceive] = useState<PlayerCard[]>([]);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [finderTrades, setFinderTrades] = useState<FinderTrade[]>([]);
  const [finding, setFinding] = useState(false);
  const [finderRan, setFinderRan] = useState(false);
  const [finderError, setFinderError] = useState<string | null>(null);

  const allIds = [...give, ...receive].map((p) => p.id);

  async function findTrades() {
    if (!league) return;
    setFinding(true);
    setFinderError(null);
    setFinderRan(false);
    try {
      const resp = await api<{ trades: FinderTrade[] }>(
        `/api/trade/finder?connection_id=${encodeURIComponent(league.id)}`,
      );
      setFinderTrades(resp.trades);
      setFinderRan(true);
    } catch (err) {
      setFinderError(err instanceof Error ? err.message : "Trade search failed");
    } finally {
      setFinding(false);
    }
  }

  function loadIntoAnalyzer(t: FinderTrade) {
    setGive([finderPlayerCard(t.give)]);
    setReceive([finderPlayerCard(t.receive)]);
    setResult(null);
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }

  async function analyze() {
    if (!league || give.length === 0 || receive.length === 0) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const resp = await api<TradeResult>("/api/trade/analyze", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league.id,
          give: give.map((p) => p.id),
          receive: receive.map((p) => p.id),
        }),
      });
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
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
        className="mx-auto max-w-5xl px-4 py-8"
      >
        <PageHeader
          title="Trade analyzer"
          description="Weigh what you give, what you get, and how the deal fits your roster."
          eyebrow="Make your move"
        />

        <div className="mt-6 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900/40">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-base font-bold">
                <Search className="h-4 w-4 text-green-600" />
                Trade Finder
              </h2>
              <p className="mt-0.5 text-sm text-gray-500">
                Auto-scan the league for fair, win-win deals that upgrade your
                lineup — no typing required.
              </p>
            </div>
            <button
              onClick={findTrades}
              disabled={finding || !league}
              className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-500 disabled:opacity-50"
            >
              {finding ? "Scanning league…" : "Find trades for me"}
            </button>
          </div>

          {finderError && (
            <p className="mt-3 text-sm text-red-500">{finderError}</p>
          )}
          {finderRan && !finding && finderTrades.length === 0 && (
            <p className="mt-3 text-sm text-gray-500">
              No clean win-win trades right now — your roster looks balanced, or
              no partner lines up on value. Try the manual analyzer below.
            </p>
          )}

          {finderTrades.length > 0 && (
            <ul className="mt-4 space-y-3">
              {finderTrades.map((t, i) => (
                <li
                  key={i}
                  className="rounded-lg border border-gray-200 p-3 dark:border-gray-800"
                >
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>
                      with <span className="font-semibold text-gray-700 dark:text-gray-300">{t.partner.owner_name}</span>{" "}
                      ({t.partner.record})
                    </span>
                    <span className="font-semibold text-green-600">
                      +{t.your_lineup_gain} pts/wk
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm font-medium">
                    <span className="text-red-500">
                      Give {t.give.name}
                      <span className="ml-1 text-xs text-gray-400">
                        {t.give.position} · {t.give.team}
                      </span>
                    </span>
                    <ArrowLeftRight className="h-4 w-4 text-gray-400" />
                    <span className="text-green-600 dark:text-green-400">
                      Get {t.receive.name}
                      <span className="ml-1 text-xs text-gray-400">
                        {t.receive.position} · {t.receive.team}
                      </span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-gray-500">{t.rationale}</p>
                  <button
                    onClick={() => loadIntoAnalyzer(t)}
                    className="mt-2 text-xs font-semibold text-green-600 hover:underline"
                  >
                    Analyze this deal →
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <TradeSide
            title="You give"
            players={give}
            setPlayers={setGive}
            excludeIds={allIds}
          />
          <TradeSide
            title="You receive"
            players={receive}
            setPlayers={setReceive}
            excludeIds={allIds}
          />
        </div>

        <div className="mt-6 flex justify-center">
          <button
            onClick={analyze}
            disabled={busy || give.length === 0 || receive.length === 0}
            className="flex items-center gap-2 rounded-lg bg-green-600 px-6 py-3 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
          >
            <ArrowLeftRight className="h-4 w-4" />
            {busy ? "Analyzing…" : "Analyze trade"}
          </button>
        </div>

        {error && (
          <p className="mt-4 text-center text-sm text-red-600">{error}</p>
        )}

        {result && (
          <div className="mt-8 space-y-4">
            {/* Trade score */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-800">
              {(() => {
                const diff = result.receive_value - result.give_value;
                const bigger = Math.max(
                  result.give_value,
                  result.receive_value,
                  1,
                );
                const meaningful = Math.abs(diff) / bigger >= 0.08;
                const verdictColor =
                  meaningful && diff > 0
                    ? "text-green-600 dark:text-green-400"
                    : meaningful && diff < 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-gray-700 dark:text-gray-300";
                return (
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-center">
                      <p className="text-xs uppercase tracking-wide text-gray-500">
                        You give
                      </p>
                      <p className="text-3xl font-extrabold tabular-nums">
                        {result.give_value.toFixed(1)}
                      </p>
                    </div>
                    <div className="flex-1 text-center">
                      <p className={`text-lg font-bold ${verdictColor}`}>
                        {result.verdict}
                      </p>
                      <div className="mx-auto mt-2 flex h-2 max-w-xs overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
                        <div
                          className="bg-red-400"
                          style={{
                            width: `${(result.give_value / Math.max(result.give_value + result.receive_value, 1)) * 100}%`,
                          }}
                        />
                        <div className="flex-1 bg-green-500" />
                      </div>
                    </div>
                    <div className="text-center">
                      <p className="text-xs uppercase tracking-wide text-gray-500">
                        You receive
                      </p>
                      <p className="text-3xl font-extrabold tabular-nums">
                        {result.receive_value.toFixed(1)}
                      </p>
                    </div>
                  </div>
                );
              })()}

              {/* Per-player values */}
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {result.player_values.map((p) => (
                  <span
                    key={p.id}
                    className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs dark:border-gray-800 dark:bg-gray-900"
                  >
                    {p.name}:{" "}
                    <strong className="tabular-nums">
                      {p.value.toFixed(1)}
                    </strong>
                    <TrendArrow trend={p.trend} />
                    {p.ppg != null && (
                      <span className="text-gray-400"> · {p.ppg} ppg</span>
                    )}
                  </span>
                ))}
              </div>

              {result.sweeteners.length > 0 && (
                <p className="mt-4 text-center text-xs text-gray-500">
                  To even it out, consider adding from your roster:{" "}
                  {result.sweeteners.map((s, i) => (
                    <span key={s.id}>
                      {i > 0 && ", "}
                      <strong>{s.name}</strong> ({s.value.toFixed(1)})
                    </span>
                  ))}
                </p>
              )}
            </div>

            <div className="prose-sm rounded-xl border border-gray-200 bg-white p-6 text-sm leading-relaxed">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ children }) => (
                    <table className="mb-3 w-full border-collapse text-xs">
                      {children}
                    </table>
                  ),
                  th: ({ children }) => (
                    <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-left font-semibold">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-gray-200 px-2 py-1">
                      {children}
                    </td>
                  ),
                }}
              >
                {result.analysis}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
