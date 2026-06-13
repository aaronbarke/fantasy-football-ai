"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import Navbar from "@/components/Navbar";
import InjuryBadge from "@/components/InjuryBadge";
import { api } from "@/lib/api";
import type { WaiverPlayer } from "@/lib/types";
import { useLeague } from "@/hooks/useLeague";
import PlayerAvatar from "@/components/PlayerAvatar";
import { Flame } from "lucide-react";

const positions = ["ALL", "QB", "RB", "WR", "TE", "K", "DEF"];

export default function WaiversPage() {
  const { league } = useLeague();
  const [filter, setFilter] = useState("ALL");

  const { data: waivers, isLoading } = useQuery({
    queryKey: ["waivers", league?.id],
    queryFn: () => api<WaiverPlayer[]>(`/api/leagues/${league!.id}/waivers`),
    enabled: !!league,
  });

  const filtered =
    waivers?.filter(
      (w) => filter === "ALL" || w.player.position === filter
    ) ?? [];

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Waiver wire</h1>
          <Link
            href={`/chat?q=${encodeURIComponent("Who should I pick up off waivers, and who should I drop?")}`}
            className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
          >
            Ask AI for pickups
          </Link>
        </div>

        <div className="mt-4 flex gap-1.5">
          {positions.map((p) => (
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

        {isLoading && <p className="mt-6 text-sm text-gray-400">Loading…</p>}
        {!isLoading && filtered.length === 0 && (
          <p className="mt-6 text-sm text-gray-400">
            No available players found — sync your league from the dashboard.
          </p>
        )}

        <ul className="mt-6 space-y-2">
          {filtered.map((w) => (
            <li
              key={w.player.id}
              className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3"
            >
              <PlayerAvatar
                id={w.player.id}
                name={w.player.name}
                position={w.player.position}
                team={w.player.team}
                size={38}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{w.player.name}</p>
                <p className="text-xs text-gray-500">
                  {w.player.position ?? "?"} · {w.player.team ?? "FA"}
                </p>
              </div>
              {w.recent_ppr_avg != null && (
                <span className="text-sm text-gray-600">
                  {w.recent_ppr_avg.toFixed(1)} ppg
                </span>
              )}
              {w.trending_count != null && (
                <span className="flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 dark:bg-orange-500/15 dark:text-orange-300">
                  <Flame className="h-3 w-3" />
                  {Intl.NumberFormat("en", { notation: "compact" }).format(
                    w.trending_count
                  )}{" "}
                  adds
                </span>
              )}
              <InjuryBadge status={w.player.injury_status} />
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
