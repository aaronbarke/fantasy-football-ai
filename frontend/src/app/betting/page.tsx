"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface PriceEntry {
  book: string;
  price: number;
  point?: number;
}

interface MlSummary {
  best: PriceEntry;
  worst_price: number;
  books: number;
  shop_value: number;
}

interface PointSummary {
  best: PriceEntry;
  range: [number, number];
  books: number;
}

interface BoardGame {
  home_team: string;
  away_team: string;
  commence_time: string | null;
  moneyline: Record<string, MlSummary | null>;
  spread: Record<string, PointSummary | null>;
  total: { over: PointSummary | null; under: PointSummary | null };
  edge_score: number;
}

function fmtPrice(p: number): string {
  return p > 0 ? `+${p}` : `${p}`;
}

function fmtPoint(p: number): string {
  return p > 0 ? `+${p}` : `${p}`;
}

export default function BettingPage() {
  useLeague(); // auth/redirect guard
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["betting-lines"],
    queryFn: () => api<{ games: BoardGame[] }>("/api/betting/lines"),
    staleTime: 10 * 60_000,
  });

  const games = data?.games ?? [];

  async function breakdown() {
    setBusy(true);
    setAnalysis(null);
    try {
      const resp = await api<{ analysis: string }>("/api/betting/analysis", {
        method: "POST",
      });
      setAnalysis(resp.analysis);
    } catch (err) {
      setAnalysis(
        `Something went wrong: ${err instanceof Error ? err.message : "unknown"}`
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Betting edge</h1>
            <p className="mt-1 text-sm text-gray-500">
              Live lines across US sportsbooks — best price highlighted, games
              sorted by how much the books disagree (line-shopping value).
            </p>
          </div>
          <button
            onClick={breakdown}
            disabled={busy || games.length === 0}
            className="flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {busy ? "Analyzing…" : "AI breakdown"}
          </button>
        </div>

        {isLoading && <p className="mt-6 text-sm text-gray-400">Pulling live lines…</p>}
        {error ? (
          <p className="mt-6 text-sm text-gray-400">
            No lines available — the books haven&apos;t posted odds yet (common in
            the offseason), or the Odds API key is missing.
          </p>
        ) : null}
        {!isLoading && !error && games.length === 0 && (
          <p className="mt-6 text-sm text-gray-400">
            No games with posted lines right now — check back closer to game week.
          </p>
        )}

        {analysis && (
          <div className="prose-sm mt-6 rounded-xl border border-green-200 bg-green-50 p-6 text-sm leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysis}</ReactMarkdown>
          </div>
        )}

        <div className="mt-6 space-y-4">
          {games.map((g) => (
            <div
              key={`${g.away_team}@${g.home_team}`}
              className="rounded-xl border border-gray-200 bg-white p-5"
            >
              <div className="flex items-center justify-between">
                <p className="font-bold">
                  {g.away_team} @ {g.home_team}
                  <span className="ml-3 text-xs font-normal text-gray-400">
                    {g.commence_time
                      ? new Date(g.commence_time).toLocaleString(undefined, {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                          hour: "numeric",
                          minute: "2-digit",
                        })
                      : ""}
                  </span>
                </p>
                {g.edge_score >= 20 && (
                  <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                    High shop value
                  </span>
                )}
              </div>

              <div className="mt-3 grid gap-4 text-sm sm:grid-cols-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Moneyline
                  </p>
                  {[g.away_team, g.home_team].map((t) => {
                    const m = g.moneyline[t];
                    return (
                      <p key={t} className="mt-1">
                        <span className="font-medium">{t}</span>{" "}
                        {m ? (
                          <>
                            <span className="font-semibold text-green-700">
                              {fmtPrice(m.best.price)}
                            </span>{" "}
                            <span className="text-xs text-gray-500">
                              @ {m.best.book}
                              {m.shop_value > 0 && ` (+${m.shop_value} vs worst)`}
                            </span>
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </p>
                    );
                  })}
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Spread
                  </p>
                  {[g.away_team, g.home_team].map((t) => {
                    const s = g.spread[t];
                    return (
                      <p key={t} className="mt-1">
                        <span className="font-medium">{t}</span>{" "}
                        {s ? (
                          <>
                            <span className="font-semibold text-green-700">
                              {fmtPoint(s.best.point!)} {fmtPrice(s.best.price)}
                            </span>{" "}
                            <span className="text-xs text-gray-500">
                              @ {s.best.book}
                              {s.range[0] !== s.range[1] &&
                                ` (books: ${fmtPoint(s.range[0])} to ${fmtPoint(s.range[1])})`}
                            </span>
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </p>
                    );
                  })}
                </div>

                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Total
                  </p>
                  {(["over", "under"] as const).map((side) => {
                    const t = g.total[side];
                    return (
                      <p key={side} className="mt-1 capitalize">
                        <span className="font-medium">{side}</span>{" "}
                        {t ? (
                          <>
                            <span className="font-semibold text-green-700">
                              {t.best.point} {fmtPrice(t.best.price)}
                            </span>{" "}
                            <span className="text-xs text-gray-500">
                              @ {t.best.book}
                              {t.range[0] !== t.range[1] &&
                                ` (${t.range[0]}–${t.range[1]})`}
                            </span>
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </p>
                    );
                  })}
                </div>
              </div>
            </div>
          ))}
        </div>

        <p className="mt-8 text-center text-xs text-gray-400">
          Lines refresh every 10 minutes. For entertainment and analysis only —
          not financial advice. 21+ where applicable.
        </p>
      </main>
    </>
  );
}
