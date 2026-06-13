"use client";

import { useState } from "react";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import type { PlayerCard } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import { ArrowLeftRight, Search, TrendingDown, TrendingUp, X } from "lucide-react";
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
      const found = await api<{ id: string; full_name: string; position: string | null; team: string | null }[]>(
        `/api/players/search?q=${encodeURIComponent(value)}`
      );
      setResults(
        found
          .filter((p) => !exclude.includes(p.id))
          .slice(0, 6)
          .map((p) => ({ id: p.id, name: p.full_name, position: p.position, team: p.team }))
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
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
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
    return <TrendingUp className="inline h-3 w-3 text-green-500" aria-label="rising" />;
  if (trend === "falling")
    return <TrendingDown className="inline h-3 w-3 text-red-500" aria-label="falling" />;
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

export default function TradePage() {
  const { league } = useLeague();
  const [give, setGive] = useState<PlayerCard[]>([]);
  const [receive, setReceive] = useState<PlayerCard[]>([]);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allIds = [...give, ...receive].map((p) => p.id);

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
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-2xl font-bold">Trade analyzer</h1>
        <p className="mt-1 text-sm text-gray-500">
          Build both sides of a trade and get a graded AI verdict. Each player
          gets a value score from Value Over Replacement — updated as the season plays out.
        </p>

        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <TradeSide title="You give" players={give} setPlayers={setGive} excludeIds={allIds} />
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

        {error && <p className="mt-4 text-center text-sm text-red-600">{error}</p>}

        {result && (
          <div className="mt-8 space-y-4">
            {/* Trade score */}
            <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-800">
              {(() => {
                const diff = result.receive_value - result.give_value;
                const bigger = Math.max(result.give_value, result.receive_value, 1);
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
                      <p className="text-xs uppercase tracking-wide text-gray-500">You give</p>
                      <p className="text-3xl font-extrabold tabular-nums">{result.give_value}</p>
                    </div>
                    <div className="flex-1 text-center">
                      <p className={`text-lg font-bold ${verdictColor}`}>{result.verdict}</p>
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
                      <p className="text-xs uppercase tracking-wide text-gray-500">You receive</p>
                      <p className="text-3xl font-extrabold tabular-nums">{result.receive_value}</p>
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
                    {p.name}: <strong className="tabular-nums">{p.value}</strong>
                    <TrendArrow trend={p.trend} />
                    {p.ppg != null && <span className="text-gray-400"> · {p.ppg} ppg</span>}
                  </span>
                ))}
              </div>

              {result.sweeteners.length > 0 && (
                <p className="mt-4 text-center text-xs text-gray-500">
                  To even it out, consider adding from your roster:{" "}
                  {result.sweeteners.map((s, i) => (
                    <span key={s.id}>
                      {i > 0 && ", "}
                      <strong>{s.name}</strong> ({s.value})
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
                    <table className="mb-3 w-full border-collapse text-xs">{children}</table>
                  ),
                  th: ({ children }) => (
                    <th className="border border-gray-200 bg-gray-50 px-2 py-1 text-left font-semibold">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-gray-200 px-2 py-1">{children}</td>
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
