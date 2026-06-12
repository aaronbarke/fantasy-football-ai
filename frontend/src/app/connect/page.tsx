"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api, setSelectedLeague } from "@/lib/api";
import type { LeagueConnection, SleeperLookup } from "@/lib/types";

export default function ConnectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [platform, setPlatform] = useState<"sleeper" | "espn">("sleeper");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sleeper flow
  const [username, setUsername] = useState("");
  const [lookup, setLookup] = useState<SleeperLookup | null>(null);

  // ESPN flow
  const [espnLeagueId, setEspnLeagueId] = useState("");
  const [espnSeason, setEspnSeason] = useState("2026");
  const [espnS2, setEspnS2] = useState("");
  const [swid, setSwid] = useState("");

  async function lookupSleeper(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const data = await api<SleeperLookup>("/api/leagues/sleeper/lookup", {
        method: "POST",
        body: JSON.stringify({ username }),
      });
      setLookup(data);
      if (data.leagues.length === 0)
        setError("No leagues found for this user in the current or previous season.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setBusy(false);
    }
  }

  async function connect(leagueId: string, season: string) {
    setError(null);
    setBusy(true);
    try {
      const conn = await api<LeagueConnection>("/api/leagues/connect", {
        method: "POST",
        body: JSON.stringify({
          platform,
          league_id: platform === "sleeper" ? leagueId : espnLeagueId,
          season: parseInt(platform === "sleeper" ? season : espnSeason, 10),
          platform_user_id: platform === "sleeper" ? lookup?.user_id : undefined,
          espn_s2: platform === "espn" && espnS2 ? espnS2 : undefined,
          swid: platform === "espn" && swid ? swid : undefined,
        }),
      });
      setSelectedLeague(conn.id);
      await queryClient.invalidateQueries({ queryKey: ["leagues"] });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-lg rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-bold">Connect your league</h1>
        <p className="mt-1 text-sm text-gray-500">
          Link a real fantasy league so the AI can see your roster.
        </p>

        <div className="mt-6 flex gap-2">
          {(["sleeper", "espn"] as const).map((p) => (
            <button
              key={p}
              onClick={() => {
                setPlatform(p);
                setError(null);
              }}
              className={`rounded-lg px-4 py-2 text-sm font-semibold capitalize ${
                platform === p
                  ? "bg-green-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {platform === "sleeper" && (
          <div className="mt-6">
            <form onSubmit={lookupSleeper} className="flex gap-2">
              <input
                required
                placeholder="Your Sleeper username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none"
              />
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
              >
                {busy ? "…" : "Find leagues"}
              </button>
            </form>

            {lookup && lookup.leagues.length > 0 && (
              <ul className="mt-4 space-y-2">
                {lookup.leagues.map((lg) => (
                  <li key={lg.league_id}>
                    <button
                      onClick={() => connect(lg.league_id, lg.season)}
                      disabled={busy}
                      className="w-full rounded-lg border border-gray-200 p-3 text-left hover:border-green-500 hover:bg-green-50 disabled:opacity-50"
                    >
                      <p className="text-sm font-semibold">{lg.name}</p>
                      <p className="text-xs text-gray-500">
                        {lg.season} · {lg.total_rosters} teams ·{" "}
                        {lg.scoring_type?.replace("_", "-").toUpperCase()}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {platform === "espn" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              connect(espnLeagueId, espnSeason);
            }}
            className="mt-6 space-y-3"
          >
            <input
              required
              placeholder="ESPN league ID"
              value={espnLeagueId}
              onChange={(e) => setEspnLeagueId(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none"
            />
            <input
              required
              placeholder="Season (e.g. 2026)"
              value={espnSeason}
              onChange={(e) => setEspnSeason(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none"
            />
            <p className="text-xs text-gray-500">
              Private league? Paste your <code>espn_s2</code> and <code>SWID</code>{" "}
              cookies (find them in your browser dev tools while logged into ESPN).
            </p>
            <input
              placeholder="espn_s2 cookie (private leagues only)"
              value={espnS2}
              onChange={(e) => setEspnS2(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none"
            />
            <input
              placeholder="SWID cookie (private leagues only)"
              value={swid}
              onChange={(e) => setSwid(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-green-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-green-600 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
            >
              {busy ? "Connecting…" : "Connect ESPN league"}
            </button>
          </form>
        )}

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      </div>
    </main>
  );
}
