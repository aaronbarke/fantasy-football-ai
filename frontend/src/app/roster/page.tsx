"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import PlayerCard from "@/components/PlayerCard";
import StatChart from "@/components/StatChart";
import { api } from "@/lib/api";
import type { PlayerCard as PlayerCardType, Roster, WeeklyStat } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import { X } from "lucide-react";

export default function RosterPage() {
  const { league } = useLeague();
  const [selected, setSelected] = useState<PlayerCardType | null>(null);

  const { data: roster, isLoading } = useQuery({
    queryKey: ["roster", league?.id],
    queryFn: () => api<Roster>(`/api/leagues/${league!.id}/roster`),
    enabled: !!league,
    retry: false,
  });

  const { data: stats } = useQuery({
    queryKey: ["player-stats", selected?.id],
    queryFn: () => api<WeeklyStat[]>(`/api/players/${selected!.id}/stats`),
    enabled: !!selected,
  });

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-2xl font-bold">Roster</h1>
        {isLoading && <p className="mt-4 text-sm text-gray-400">Loading…</p>}
        {!isLoading && !roster && (
          <p className="mt-4 text-sm text-gray-400">
            No roster found — sync your league from the dashboard.
          </p>
        )}

        {roster && (
          <div className="mt-6 grid gap-8 lg:grid-cols-2">
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                Starters
              </h2>
              <div className="mt-3 space-y-2">
                {roster.starters.map((p, i) => (
                  <button
                    key={`${p.id}-${i}`}
                    onClick={() => setSelected(p)}
                    className="block w-full text-left"
                  >
                    <PlayerCard player={p} />
                  </button>
                ))}
              </div>
            </section>
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                Bench
              </h2>
              <div className="mt-3 space-y-2">
                {roster.bench.map((p, i) => (
                  <button
                    key={`${p.id}-${i}`}
                    onClick={() => setSelected(p)}
                    className="block w-full text-left"
                  >
                    <PlayerCard player={p} />
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}

        {selected && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            onClick={() => setSelected(null)}
          >
            <div
              className="w-full max-w-lg rounded-xl bg-white p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-bold">{selected.name}</h3>
                  <p className="text-sm text-gray-500">
                    {selected.position} · {selected.team ?? "FA"}
                    {selected.injury_status ? ` · ${selected.injury_status}` : ""}
                  </p>
                </div>
                <button
                  onClick={() => setSelected(null)}
                  className="rounded-md p-1 hover:bg-gray-100"
                >
                  <X className="h-5 w-5 text-gray-400" />
                </button>
              </div>
              <div className="mt-4">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Recent fantasy points (PPR)
                </h4>
                <div className="mt-2">
                  {stats ? (
                    <StatChart stats={stats} />
                  ) : (
                    <p className="text-sm text-gray-400">Loading stats…</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
