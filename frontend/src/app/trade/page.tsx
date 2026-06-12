"use client";

import { useState } from "react";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import type { PlayerCard } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import { ArrowLeftRight, Search, X } from "lucide-react";
import ReactMarkdown from "react-markdown";

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

export default function TradePage() {
  const { league } = useLeague();
  const [give, setGive] = useState<PlayerCard[]>([]);
  const [receive, setReceive] = useState<PlayerCard[]>([]);
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allIds = [...give, ...receive].map((p) => p.id);

  async function analyze() {
    if (!league || give.length === 0 || receive.length === 0) return;
    setBusy(true);
    setError(null);
    setAnalysis(null);
    try {
      const resp = await api<{ analysis: string }>("/api/trade/analyze", {
        method: "POST",
        body: JSON.stringify({
          connection_id: league.id,
          give: give.map((p) => p.id),
          receive: receive.map((p) => p.id),
        }),
      });
      setAnalysis(resp.analysis);
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
          Build both sides of a trade and get a graded AI verdict.
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

        {analysis && (
          <div className="prose-sm mt-8 rounded-xl border border-gray-200 bg-white p-6 text-sm leading-relaxed">
            <ReactMarkdown>{analysis}</ReactMarkdown>
          </div>
        )}
      </main>
    </>
  );
}
