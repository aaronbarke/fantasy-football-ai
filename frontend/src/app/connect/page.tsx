"use client";

import { useState } from "react";
import Link from "next/link";
import Brand from "@/components/Brand";
import { ArrowRight, Check, ShieldCheck } from "lucide-react";
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
        setError(
          "No leagues found for this user in the current or previous season.",
        );
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
          platform_user_id:
            platform === "sleeper" ? lookup?.user_id : undefined,
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
    <main className="mx-auto min-h-screen max-w-5xl px-5 py-8 sm:px-10">
      <div className="flex items-center justify-between">
        <Brand href="/" />
        <Link href="/dashboard" className="text-xs font-medium text-gray-500">
          Back to workspace →
        </Link>
      </div>
      <div className="mx-auto mt-12 max-w-lg sm:mt-20">
        <div className="mb-8 flex items-center gap-3 text-[10px] font-semibold uppercase tracking-widest text-gray-500">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-green-100 text-green-700">
            <Check className="h-3 w-3" />
          </span>
          Account
          <span className="h-px flex-1 bg-gray-200" />
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-green-700 text-white">
            2
          </span>
          Your league
        </div>
        <p className="eyebrow">Make it personal</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight">
          Bring your league.
        </h1>
        <p className="mt-4 text-sm leading-7 text-gray-500">
          Connect your roster, matchups, and league settings. Start with the
          platform you play on.
        </p>
        <div className="mt-8 rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
          <div
            className="grid grid-cols-2 gap-2 rounded-xl bg-gray-50 p-1"
            aria-label="Fantasy platform"
          >
            {(["sleeper", "espn"] as const).map((p) => (
              <button
                key={p}
                aria-pressed={platform === p}
                disabled={busy}
                onClick={() => {
                  setPlatform(p);
                  setError(null);
                }}
                className={`rounded-lg px-4 py-3 text-sm font-semibold ${platform === p ? "bg-green-700 text-white" : "text-gray-500 hover:bg-gray-100"}`}
              >
                {p === "espn" ? "ESPN" : "Sleeper"}
              </button>
            ))}
          </div>
          {platform === "sleeper" && (
            <div className="mt-7">
              <form onSubmit={lookupSleeper}>
                <label className="field-label" htmlFor="sleeper-username">
                  Sleeper username
                </label>
                <input
                  id="sleeper-username"
                  required
                  autoComplete="username"
                  placeholder="Your username, not your team name"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="form-input"
                />
                <p className="mt-2 text-xs leading-5 text-gray-500">
                  No Sleeper password needed. We’ll find leagues linked to your
                  username.
                </p>
                <button
                  type="submit"
                  disabled={busy}
                  className="button-primary mt-5 w-full"
                >
                  {busy ? "Finding your leagues…" : "Find my leagues"}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </form>
              {lookup && lookup.leagues.length > 0 && (
                <div className="mt-6">
                  <p className="field-label">Choose a league to connect</p>
                  <ul className="space-y-2">
                    {lookup.leagues.map((lg) => (
                      <li key={lg.league_id}>
                        <button
                          onClick={() => connect(lg.league_id, lg.season)}
                          disabled={busy}
                          className="w-full rounded-lg border border-gray-200 p-4 text-left hover:border-green-500 hover:bg-green-50 disabled:opacity-50"
                        >
                          <p className="text-sm font-semibold">{lg.name}</p>
                          <p className="mt-1 text-xs text-gray-500">
                            {lg.season} · {lg.total_rosters} teams ·{" "}
                            {lg.scoring_type?.replace("_", "-").toUpperCase()}
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          {platform === "espn" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                connect(espnLeagueId, espnSeason);
              }}
              className="mt-7 space-y-5"
            >
              <div>
                <label className="field-label" htmlFor="espn-league">
                  League ID
                </label>
                <input
                  id="espn-league"
                  required
                  inputMode="numeric"
                  placeholder="e.g. 12345678"
                  value={espnLeagueId}
                  onChange={(e) => setEspnLeagueId(e.target.value)}
                  className="form-input"
                />
                <p className="mt-2 text-xs leading-5 text-gray-500">
                  The number after leagueId= in your ESPN league’s web address.
                </p>
              </div>
              <div>
                <label className="field-label" htmlFor="espn-season">
                  Season
                </label>
                <input
                  id="espn-season"
                  required
                  type="number"
                  min="2000"
                  max="2100"
                  value={espnSeason}
                  onChange={(e) => setEspnSeason(e.target.value)}
                  className="form-input"
                />
              </div>
              <details className="rounded-xl border border-gray-200 p-4">
                <summary className="cursor-pointer text-xs font-semibold">
                  Playing in a private league?
                </summary>
                <p className="mt-3 text-xs leading-6 text-gray-500">
                  Private leagues need your ESPN session cookies. While signed
                  into ESPN, open your browser’s developer tools and look under
                  Application → Cookies for espn_s2 and SWID.
                </p>
                <label className="field-label mt-4" htmlFor="espn-cookie">
                  espn_s2
                </label>
                <input
                  id="espn-cookie"
                  type="password"
                  autoComplete="off"
                  placeholder="Paste your espn_s2 cookie"
                  value={espnS2}
                  onChange={(e) => setEspnS2(e.target.value)}
                  className="form-input"
                />
                <label className="field-label mt-4" htmlFor="espn-swid">
                  SWID
                </label>
                <input
                  id="espn-swid"
                  type="password"
                  autoComplete="off"
                  placeholder="Paste your SWID cookie"
                  value={swid}
                  onChange={(e) => setSwid(e.target.value)}
                  className="form-input"
                />
              </details>
              <button
                type="submit"
                disabled={busy}
                className="button-primary w-full"
              >
                {busy ? "Connecting your league…" : "Connect my league"}
                <ArrowRight className="h-4 w-4" />
              </button>
            </form>
          )}
          {error && (
            <p role="alert" className="mt-4 text-sm text-red-600">
              {error}
            </p>
          )}
        </div>
        <p className="mt-6 flex items-start justify-center gap-2 text-xs leading-6 text-gray-500">
          <ShieldCheck className="mt-1 h-4 w-4 shrink-0" />
          Connecting imports league data. Lineup changes stay on your fantasy
          platform.
        </p>
        <Link
          href="/draft"
          className="mt-7 block text-center text-xs font-semibold text-green-700"
        >
          Just preparing? Explore the draft room →
        </Link>
      </div>
    </main>
  );
}
