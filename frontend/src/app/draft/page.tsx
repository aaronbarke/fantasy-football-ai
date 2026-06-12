"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Navbar from "@/components/Navbar";
import { api } from "@/lib/api";
import { useLeague } from "@/hooks/useLeague";
import { positionColor } from "@/lib/utils";
import { RotateCcw, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface RankedPlayer {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  injury_status: string | null;
  avg_ppr: number;
  games: number;
  season: number;
}

type DraftMark = "me" | "gone";
const positions = ["ALL", "QB", "RB", "WR", "TE"];

export default function DraftPage() {
  const { league } = useLeague();
  const [drafted, setDrafted] = useState<Record<string, DraftMark>>({});
  const [filter, setFilter] = useState("ALL");
  const [advice, setAdvice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("draft_state");
      if (saved) setDrafted(JSON.parse(saved));
    } catch {
      /* corrupt state — start fresh */
    }
  }, []);

  function mark(id: string, value: DraftMark | null) {
    setDrafted((d) => {
      const next = { ...d };
      if (value === null) delete next[id];
      else next[id] = value;
      localStorage.setItem("draft_state", JSON.stringify(next));
      return next;
    });
  }

  const { data: rankings, isLoading } = useQuery({
    queryKey: ["rankings"],
    queryFn: () => api<RankedPlayer[]>("/api/players/rankings?limit=300"),
    staleTime: 60 * 60_000,
  });

  const available = (rankings ?? []).filter((p) => !drafted[p.id]);
  const filtered = available.filter((p) => filter === "ALL" || p.position === filter);
  const myPicks = (rankings ?? []).filter((p) => drafted[p.id] === "me");
  const totalPicked = Object.keys(drafted).length;

  // Positional scarcity: how many startable players remain per position
  const remaining: Record<string, number> = {};
  for (const p of available.slice(0, 120)) {
    if (p.position) remaining[p.position] = (remaining[p.position] ?? 0) + 1;
  }

  async function askAI() {
    setBusy(true);
    setAdvice(null);
    try {
      const round = Math.floor(myPicks.length) + 1;
      const top = filtered.slice(0, 15).map((p) => `${p.name} (${p.position}, ${p.avg_ppr} ppg)`);
      const mine = myPicks.map((p) => `${p.name} (${p.position})`);
      const message =
        `I'm in a live draft (my round ${round}, ${totalPicked} players off the board). ` +
        `My picks so far: ${mine.length ? mine.join(", ") : "none yet"}. ` +
        `Top available by last-season PPR: ${top.join(", ")}. ` +
        `Who should I take next and why? Consider positional scarcity and roster construction. Give top 3 options.`;
      const resp = await api<{ response: string }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message, connection_id: league?.id ?? null }),
      });
      setAdvice(resp.response);
    } catch (err) {
      setAdvice(`Something went wrong: ${err instanceof Error ? err.message : "unknown"}`);
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
            <h1 className="text-2xl font-bold">Draft assistant</h1>
            <p className="mt-1 text-sm text-gray-500">
              Mark picks as they happen — rankings from last season&apos;s PPR
              points per game.
            </p>
          </div>
          <button
            onClick={() => {
              localStorage.removeItem("draft_state");
              setDrafted({});
              setAdvice(null);
            }}
            className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100"
          >
            <RotateCcw className="h-4 w-4" /> Reset draft
          </button>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          {/* Available players */}
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between">
              <div className="flex gap-1.5">
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
                    {p !== "ALL" && remaining[p] != null && (
                      <span className="ml-1 opacity-70">({remaining[p]})</span>
                    )}
                  </button>
                ))}
              </div>
              <span className="text-xs text-gray-500">{totalPicked} drafted</span>
            </div>

            {isLoading && <p className="mt-4 text-sm text-gray-400">Loading rankings…</p>}
            {!isLoading && (rankings ?? []).length === 0 && (
              <p className="mt-4 text-sm text-gray-400">
                No rankings — seed player stats first (see README).
              </p>
            )}

            <ul className="mt-3 max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
              {filtered.slice(0, 100).map((p, i) => (
                <li
                  key={p.id}
                  className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-2.5"
                >
                  <span className="w-6 text-right text-xs text-gray-400">{i + 1}</span>
                  <span
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                  >
                    {p.position}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{p.name}</p>
                    <p className="text-xs text-gray-500">
                      {p.team ?? "FA"} · {p.avg_ppr} ppg ({p.season})
                    </p>
                  </div>
                  <button
                    onClick={() => mark(p.id, "me")}
                    className="rounded-md bg-green-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-green-700"
                  >
                    My pick
                  </button>
                  <button
                    onClick={() => mark(p.id, "gone")}
                    className="rounded-md border border-gray-300 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
                  >
                    Gone
                  </button>
                </li>
              ))}
            </ul>
          </div>

          {/* My roster + AI advice */}
          <div className="space-y-4">
            <div className="rounded-xl border border-gray-200 bg-white p-5">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
                My roster ({myPicks.length})
              </h2>
              <ul className="mt-3 space-y-1.5">
                {myPicks.map((p) => (
                  <li key={p.id} className="flex items-center gap-2 text-sm">
                    <span
                      className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-bold text-white ${positionColor(p.position)}`}
                    >
                      {p.position}
                    </span>
                    <span className="flex-1 truncate font-medium">{p.name}</span>
                    <button
                      onClick={() => mark(p.id, null)}
                      className="text-xs text-gray-400 hover:text-red-500"
                    >
                      undo
                    </button>
                  </li>
                ))}
                {myPicks.length === 0 && (
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
              {busy ? "Thinking…" : "Who should I take next?"}
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
