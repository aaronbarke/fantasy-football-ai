"use client";

import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import type { PlayerCard, WeeklyStat } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import { Search, X } from "lucide-react";
import {
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = ["#16a34a", "#2563eb", "#ea580c"];
const METRICS = [
  { key: "fantasy_points_ppr", label: "PPR points" },
  { key: "targets", label: "Targets" },
  { key: "receiving_yards", label: "Receiving yards" },
  { key: "rush_yards", label: "Rushing yards" },
] as const;

export default function ComparePage() {
  useLeague(); // auth/redirect guard
  const [players, setPlayers] = useState<PlayerCard[]>([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PlayerCard[]>([]);
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>(
    "fantasy_points_ppr"
  );
  const [range, setRange] = useState<"season" | "last10" | "last5">("season");

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
          .filter((p) => !players.some((x) => x.id === p.id))
          .slice(0, 6)
          .map((p) => ({ id: p.id, name: p.full_name, position: p.position, team: p.team }))
      );
    } catch {
      setResults([]);
    }
  }

  const statQueries = useQueries({
    queries: players.map((p) => ({
      queryKey: ["player-stats", p.id],
      queryFn: () => api<WeeklyStat[]>(`/api/players/${p.id}/stats`),
    })),
  });

  // Merge each player's selected window into one chart dataset keyed by season-week
  const merged: Record<string, Record<string, number | string>> = {};
  const averages: (number | null)[] = [];
  statQueries.forEach((sq, idx) => {
    // Regular season only — weeks 19+ are playoffs, fantasy ends week 18
    const sorted = (sq.data ?? [])
      .filter((s) => s.week <= 18)
      .sort((a, b) => a.season - b.season || a.week - b.week);
    let stats = sorted;
    if (range === "season") {
      // Full most-recent season for this player, from week 1
      const latest = sorted.length ? sorted[sorted.length - 1].season : null;
      stats = sorted.filter((s) => s.season === latest);
    } else {
      stats = sorted.slice(range === "last10" ? -10 : -5);
    }
    const values: number[] = [];
    for (const s of stats) {
      // Zero-pad the week so string sorting matches chronological order
      const key = `${s.season}W${String(s.week).padStart(2, "0")}`;
      merged[key] ??= { label: `W${s.week}` };
      const v = Number((s as unknown as Record<string, number | null>)[metric] ?? 0);
      merged[key][players[idx].name] = v;
      values.push(v);
    }
    averages[idx] = values.length
      ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10
      : null;
  });
  // Full-season view: show every week 1-18 so byes and missed games appear
  // as gaps in the line instead of being silently skipped.
  if (range === "season" && Object.keys(merged).length > 0) {
    const season = Object.keys(merged).sort().slice(-1)[0].split("W")[0];
    for (let w = 1; w <= 18; w++) {
      const key = `${season}W${String(w).padStart(2, "0")}`;
      merged[key] ??= { label: `W${w}` };
    }
  }
  const chartData = Object.entries(merged)
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([, v]) => v);

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <h1 className="text-2xl font-bold">Compare players</h1>
        <p className="mt-1 text-sm text-gray-500">
          Overlay up to 3 players to see who&apos;s trending up.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {players.map((p, i) => (
            <span
              key={p.id}
              className="flex items-center gap-2 rounded-full border border-gray-200 bg-white py-1 pl-1 pr-2 text-sm"
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold text-white ${positionColor(p.position)}`}
                style={{ backgroundColor: COLORS[i] }}
              >
                {p.position}
              </span>
              {p.name}
              <button
                onClick={() => setPlayers(players.filter((x) => x.id !== p.id))}
                aria-label={`Remove ${p.name}`}
              >
                <X className="h-3.5 w-3.5 text-gray-400" />
              </button>
            </span>
          ))}

          {players.length < 3 && (
            <div className="relative">
              <div className="flex items-center gap-2 rounded-full border border-gray-300 px-3 py-1.5">
                <Search className="h-3.5 w-3.5 text-gray-400" />
                <input
                  value={q}
                  onChange={(e) => search(e.target.value)}
                  placeholder="Add player…"
                  className="w-36 border-0 bg-transparent text-sm focus:outline-none"
                />
              </div>
              {results.length > 0 && (
                <div className="absolute left-0 top-full z-20 mt-1 w-64 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                  {results.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        setPlayers([...players, p]);
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
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          {(
            [
              { key: "season", label: "Full season" },
              { key: "last10", label: "Last 10" },
              { key: "last5", label: "Last 5" },
            ] as const
          ).map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                range === r.key
                  ? "bg-gray-800 text-white dark:bg-gray-200 dark:text-gray-900"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {r.label}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-gray-300" />
          {METRICS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMetric(m.key)}
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                metric === m.key
                  ? "bg-green-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="mt-6 rounded-xl border border-gray-200 bg-white p-4">
          {players.length > 0 && (
            <div className="mb-2 flex flex-wrap justify-end gap-3 text-sm font-semibold">
              {players.map((p, i) =>
                averages[i] != null ? (
                  <span key={p.id} style={{ color: COLORS[i] }}>
                    {p.name.split(" ").slice(-1)[0]} avg: {averages[i]}
                  </span>
                ) : null
              )}
            </div>
          )}
          {players.length === 0 ? (
            <p className="py-16 text-center text-sm text-gray-400">
              Add players above to start comparing.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <XAxis dataKey="label" fontSize={12} tickLine={false} />
                <YAxis fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip />
                <Legend />
                {players.map((p, i) => (
                  <Line
                    key={p.id}
                    type="monotone"
                    dataKey={p.name}
                    stroke={COLORS[i]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </main>
    </>
  );
}
