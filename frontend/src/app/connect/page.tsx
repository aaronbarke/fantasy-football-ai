"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Brand from "@/components/Brand";
import { ArrowRight, Check, Download, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api, setSelectedLeague } from "@/lib/api";
import {
  ESPN_EXTENSION_STORE_URL,
  ESPN_EXTENSION_ZIP,
  EspnExtensionError,
  currentFantasySeason,
  detectEspnExtension,
  normalizeSwid,
  parseEspnCookies,
  parseEspnLeague,
  requestEspnCookies,
  type EspnCookies,
  type EspnLeagueOption,
  type EspnRefreshedLeague,
} from "@/lib/espn";
import type { LeagueConnection, SleeperLookup } from "@/lib/types";

const ESPN_SIGN_IN_URL = "https://www.espn.com/fantasy/football/";

export default function ConnectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [platform, setPlatform] = useState<"sleeper" | "espn">("sleeper");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sleeper flow
  const [username, setUsername] = useState("");
  const [lookup, setLookup] = useState<SleeperLookup | null>(null);

  // ESPN flow. One click with the FFAI Connect extension: it shares this
  // browser's ESPN sign-in, and we list the account's leagues to pick from.
  const [extension, setExtension] = useState<"checking" | "ready" | "missing">("checking");
  const [espnCookies, setEspnCookies] = useState<EspnCookies | null>(null);
  const [espnLeagues, setEspnLeagues] = useState<EspnLeagueOption[] | null>(null);
  const [espnNotice, setEspnNotice] = useState<string | null>(null);
  const [espnSignedOut, setEspnSignedOut] = useState(false);
  // ESPN manual fallback: public leagues, or browsers without the extension.
  const [manualOpen, setManualOpen] = useState(false);
  const [espnLeagueId, setEspnLeagueId] = useState("");
  const [espnSeason, setEspnSeason] = useState(() => String(currentFantasySeason()));
  const [espnS2, setEspnS2] = useState("");
  const [swid, setSwid] = useState("");

  useEffect(() => {
    // "Reconnect ESPN" links land here with ?platform=espn.
    if (new URLSearchParams(window.location.search).get("platform") === "espn") {
      setPlatform("espn");
    }
    let cancelled = false;
    detectEspnExtension().then((found) => {
      if (!cancelled) setExtension(found ? "ready" : "missing");
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function resetMessages() {
    setError(null);
    setEspnNotice(null);
    setEspnSignedOut(false);
  }

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

  async function connect(body: Record<string, unknown>) {
    resetMessages();
    setBusy(true);
    try {
      const conn = await api<LeagueConnection>("/api/leagues/connect", {
        method: "POST",
        body: JSON.stringify(body),
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

  /** Extension path: read the ESPN sign-in, list the account's leagues, and
   * while we hold fresh cookies, repair any league already connected. */
  async function findEspnLeagues() {
    resetMessages();
    setBusy(true);
    try {
      const cookies = await requestEspnCookies();
      setEspnCookies(cookies);
      let found: EspnLeagueOption[];
      try {
        const data = await api<{ leagues: EspnLeagueOption[] }>(
          "/api/leagues/espn/lookup",
          { method: "POST", body: JSON.stringify(cookies) },
        );
        found = data.leagues;
      } catch (err) {
        // The sign-in is in hand, so the league's address is all that's missing.
        setManualOpen(true);
        throw err;
      }
      setEspnLeagues(found);
      setManualOpen(found.length === 0);
      if (found.length === 0) {
        setEspnNotice(
          "ESPN didn't list any fantasy football leagues for this account. Add the league by its web address below — your ESPN sign-in is already attached.",
        );
      }
      if (found.some((lg) => lg.connected)) {
        try {
          const refreshed = await api<{ leagues: EspnRefreshedLeague[] }>(
            "/api/leagues/espn/credentials",
            { method: "POST", body: JSON.stringify(cookies) },
          );
          const ok = refreshed.leagues.filter((lg) => lg.ok).length;
          if (ok > 0) {
            setEspnNotice(
              `ESPN access refreshed for ${ok} connected league${ok === 1 ? "" : "s"}.`,
            );
            await queryClient.invalidateQueries({ queryKey: ["leagues"] });
          }
        } catch {
          /* the list is still good; the leagues can be refreshed from Overview */
        }
      }
    } catch (err) {
      if (err instanceof EspnExtensionError) {
        if (err.reason === "missing") setExtension("missing");
        setEspnSignedOut(err.reason === "signed_out");
      }
      setError(err instanceof Error ? err.message : "Couldn't reach ESPN");
    } finally {
      setBusy(false);
    }
  }

  function connectEspnManually(e: React.FormEvent) {
    e.preventDefault();
    const { leagueId } = parseEspnLeague(espnLeagueId);
    if (!/^\d+$/.test(leagueId)) {
      resetMessages();
      setError("Paste your league's web address, or just its numeric league ID.");
      return;
    }
    const s2 = espnCookies?.espn_s2 ?? espnS2.trim();
    const id = espnCookies?.swid ?? (swid.trim() ? normalizeSwid(swid) : "");
    if (Boolean(s2) !== Boolean(id)) {
      resetMessages();
      setError("A private league needs both values: espn_s2 and SWID.");
      return;
    }
    void connect({
      platform: "espn",
      league_id: leagueId,
      season: parseInt(espnSeason, 10),
      espn_s2: s2 || undefined,
      swid: id || undefined,
    });
  }

  /** A pasted league web address also sets the season; the league ID is read
   * out of it on submit (rewriting the box mid-typing would mangle it). */
  function onLeagueInput(value: string) {
    setEspnLeagueId(value);
    const { season } = parseEspnLeague(value);
    if (season) setEspnSeason(season);
  }

  /** Either cookie box takes a whole pasted Cookie header, cURL command or
   * cookie-table rows and sorts the two values into place. */
  function onCookieInput(value: string, field: "espn_s2" | "swid") {
    const found = parseEspnCookies(value);
    if (found.espn_s2 || found.swid) {
      if (found.espn_s2) setEspnS2(found.espn_s2);
      if (found.swid) setSwid(found.swid);
      return;
    }
    if (field === "espn_s2") setEspnS2(value.trim());
    else setSwid(value.trim());
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
        <div className="mb-8 flex items-center gap-3 text-xs font-semibold text-gray-500">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-accent">
            <Check className="h-3 w-3" />
          </span>
          Account
          <span className="h-px flex-1 bg-gray-200" />
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-canvas">
            2
          </span>
          Your league
        </div>
        <p className="eyebrow">Last step</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight">
          Bring your league.
        </h1>
        <p className="mt-4 text-sm leading-7 text-gray-500">
          We’ll bring in your roster, matchups, and league settings. Pick the
          platform you play on.
        </p>
        <div className="mt-8 rounded-2xl border border-gray-200 bg-white p-6 sm:p-8">
          <div
            className="segmented grid w-full grid-cols-2"
            aria-label="Fantasy platform"
          >
            {(["sleeper", "espn"] as const).map((p) => (
              <button
                key={p}
                aria-pressed={platform === p}
                disabled={busy}
                onClick={() => {
                  setPlatform(p);
                  resetMessages();
                }}
                className={`rounded-lg px-4 py-2.5 text-sm font-semibold ${platform === p ? "chip-active" : "text-gray-500 hover:text-ink"}`}
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
                          onClick={() =>
                            connect({
                              platform: "sleeper",
                              league_id: lg.league_id,
                              season: parseInt(lg.season, 10),
                              platform_user_id: lookup.user_id,
                            })
                          }
                          disabled={busy}
                          className="w-full rounded-lg border border-gray-200 p-4 text-left hover:border-accent/50 hover:bg-accent-soft/40 disabled:opacity-50"
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
            <div className="mt-7 space-y-5">
              {extension === "ready" ? (
                <div>
                  <button
                    type="button"
                    onClick={findEspnLeagues}
                    disabled={busy}
                    className="button-primary w-full"
                  >
                    {busy ? "Checking ESPN…" : "Find my ESPN leagues"}
                    <ArrowRight className="h-4 w-4" />
                  </button>
                  <p className="mt-2 text-xs leading-5 text-gray-500">
                    The FFAI Connect extension shares your ESPN sign-in from
                    this browser. No password, nothing to copy.
                  </p>
                </div>
              ) : extension === "missing" ? (
                <div className="rounded-xl border border-gray-200 p-4">
                  <p className="text-sm font-semibold">Connect in one click</p>
                  <p className="mt-1 text-xs leading-6 text-gray-500">
                    Private ESPN leagues need your ESPN sign-in. The FFAI
                    Connect browser extension hands it over for you, so
                    there’s nothing to dig out of developer tools — and when
                    ESPN signs you out, one click fixes every league.
                  </p>
                  {ESPN_EXTENSION_STORE_URL ? (
                    <a
                      href={ESPN_EXTENSION_STORE_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="button-primary mt-4 w-full"
                    >
                      Get the extension
                      <ArrowRight className="h-4 w-4" />
                    </a>
                  ) : (
                    <>
                      <a
                        href={ESPN_EXTENSION_ZIP}
                        download
                        className="button-primary mt-4 w-full"
                      >
                        <Download className="h-4 w-4" />
                        Download the extension
                      </a>
                      <ol className="mt-4 list-decimal space-y-1 pl-5 text-xs leading-6 text-gray-500">
                        <li>Unzip the download.</li>
                        <li>
                          Open <span className="font-mono">chrome://extensions</span>{" "}
                          and turn on Developer mode.
                        </li>
                        <li>
                          Choose “Load unpacked” and pick the unzipped folder.
                        </li>
                      </ol>
                      <p className="mt-2 text-xs leading-5 text-gray-500">
                        Works in Chrome, Edge, Brave and Arc on a computer.
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      // Extensions only attach to pages loaded after install.
                      window.location.href = "/connect?platform=espn";
                    }}
                    className="button-secondary mt-3 w-full"
                  >
                    I’ve installed it
                  </button>
                </div>
              ) : (
                <button type="button" disabled className="button-primary w-full">
                  Checking for the extension…
                </button>
              )}

              {espnNotice && (
                <p role="status" className="text-xs leading-5 text-gray-500">
                  {espnNotice}
                </p>
              )}

              {espnLeagues && espnLeagues.length > 0 && (
                <div>
                  <p className="field-label">Choose a league to connect</p>
                  <ul className="space-y-2">
                    {espnLeagues.map((lg) => (
                      <li key={`${lg.league_id}-${lg.season}`}>
                        <button
                          type="button"
                          onClick={() =>
                            connect({
                              platform: "espn",
                              league_id: lg.league_id,
                              season: lg.season,
                              espn_s2: espnCookies?.espn_s2,
                              swid: espnCookies?.swid,
                              team_id: lg.team_id ?? undefined,
                            })
                          }
                          disabled={busy || lg.connected}
                          className="w-full rounded-lg border border-gray-200 p-4 text-left hover:border-accent/50 hover:bg-accent-soft/40 disabled:opacity-60 disabled:hover:border-gray-200 disabled:hover:bg-transparent"
                        >
                          <span className="flex items-center justify-between gap-3">
                            <span className="text-sm font-semibold">{lg.name}</span>
                            {lg.connected && (
                              <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-gray-500">
                                <Check className="h-3 w-3" />
                                Connected
                              </span>
                            )}
                          </span>
                          <span className="mt-1 block text-xs text-gray-500">
                            {[
                              lg.season,
                              lg.total_teams ? `${lg.total_teams} teams` : null,
                              lg.team_name,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <details
                className="rounded-xl border border-gray-200 p-4"
                open={manualOpen}
                onToggle={(e) => setManualOpen(e.currentTarget.open)}
              >
                <summary className="cursor-pointer text-xs font-semibold">
                  Add a league by its web address instead
                </summary>
                <form onSubmit={connectEspnManually} className="mt-4 space-y-5">
                  <div>
                    <label className="field-label" htmlFor="espn-league">
                      League web address or ID
                    </label>
                    <input
                      id="espn-league"
                      required
                      placeholder="Paste the address of your ESPN league page"
                      value={espnLeagueId}
                      onChange={(e) => onLeagueInput(e.target.value)}
                      className="form-input"
                    />
                    <p className="mt-2 text-xs leading-5 text-gray-500">
                      Copy it from your browser while your league is open on
                      ESPN. A public league needs nothing else.
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
                  {espnCookies ? (
                    <p className="flex items-center gap-2 text-xs font-medium text-gray-500">
                      <Check className="h-3.5 w-3.5" />
                      Your ESPN sign-in is attached, so private leagues work.
                    </p>
                  ) : (
                    <div>
                      <p className="text-xs font-semibold">Private league</p>
                      <p className="mt-1 text-xs leading-6 text-gray-500">
                        Without the extension, a private league needs two
                        cookies from your ESPN session: espn_s2 and SWID.
                        Paste them one at a time, or paste a whole Cookie
                        header into either box and both are picked out.
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
                        onChange={(e) => onCookieInput(e.target.value, "espn_s2")}
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
                        onChange={(e) => onCookieInput(e.target.value, "swid")}
                        className="form-input"
                      />
                    </div>
                  )}
                  <button
                    type="submit"
                    disabled={busy}
                    className="button-primary w-full"
                  >
                    {busy ? "Connecting your league…" : "Connect my league"}
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </form>
              </details>
            </div>
          )}
          {error && (
            <p role="alert" className="mt-4 text-sm text-red-600">
              {error}
              {espnSignedOut && (
                <>
                  {" "}
                  <a
                    href={ESPN_SIGN_IN_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold underline"
                  >
                    Open ESPN
                  </a>
                </>
              )}
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
          className="mt-7 block text-center text-xs font-semibold text-accent-ink"
        >
          Just preparing? Explore the draft room →
        </Link>
      </div>
    </main>
  );
}
