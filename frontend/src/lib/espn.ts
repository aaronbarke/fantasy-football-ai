/** Connecting ESPN leagues: talking to the FFAI Connect browser extension, and
 * forgiving parsers for the manual fallback.
 *
 * ESPN keeps a session in two cookies, espn_s2 and SWID. espn_s2 is HttpOnly,
 * so this page can never read it itself; the extension (see /extension in the
 * repo) reads both from the browser and hands them over when the page asks. */

export interface EspnCookies {
  espn_s2: string;
  swid: string;
}

export interface EspnLeagueOption {
  league_id: string;
  name: string;
  season: number;
  team_id: string | null;
  team_name: string | null;
  total_teams: number | null;
  connected: boolean;
}

export interface EspnRefreshedLeague {
  id: string;
  league_name: string | null;
  ok: boolean;
  detail: string | null;
}

// Message tags shared with extension/content.js.
const APP = "ffai-app";
const EXTENSION = "ffai-espn-extension";

export type EspnExtensionFailure =
  | "missing" // no extension answered
  | "signed_out" // not signed in to ESPN in this browser
  | "no_gesture" // asked without a click
  | "stale" // extension updated while this tab was open
  | "error";

const FAILURE_MESSAGES: Record<EspnExtensionFailure, string> = {
  missing:
    "The FFAI Connect extension didn't answer. Install it (or reload this page if you just did), then try again.",
  signed_out:
    "You're not signed in to ESPN in this browser. Sign in at espn.com, then try again.",
  no_gesture: "Click the button again to share your ESPN sign-in.",
  stale: "The extension was just updated. Reload this page, then try again.",
  error: "The extension couldn't read your ESPN sign-in. Reload this page and try again.",
};

export class EspnExtensionError extends Error {
  reason: EspnExtensionFailure;
  constructor(reason: EspnExtensionFailure) {
    super(FAILURE_MESSAGES[reason]);
    this.reason = reason;
  }
}

type ExtensionMessage = {
  source?: string;
  type?: string;
  requestId?: string;
  ok?: boolean;
  reason?: string;
  espn_s2?: string;
  swid?: string;
};

/** Wait for one message from the extension that `accept` recognises. */
function waitForExtension<T>(
  ask: Record<string, unknown>,
  accept: (data: ExtensionMessage) => T | undefined,
  timeoutMs: number,
): Promise<T | undefined> {
  return new Promise((resolve) => {
    const finish = (value: T | undefined) => {
      window.removeEventListener("message", onMessage);
      clearTimeout(timer);
      resolve(value);
    };
    const onMessage = (event: MessageEvent) => {
      // Only this window's own extension script — never another frame or tab.
      if (event.source !== window || event.origin !== window.location.origin) return;
      const data = event.data as ExtensionMessage | null;
      if (!data || data.source !== EXTENSION) return;
      const value = accept(data);
      if (value !== undefined) finish(value);
    };
    const timer = setTimeout(() => finish(undefined), timeoutMs);
    window.addEventListener("message", onMessage);
    window.postMessage({ source: APP, ...ask }, window.location.origin);
  });
}

/** Is the FFAI Connect extension installed and active on this page? */
export async function detectEspnExtension(timeoutMs = 700): Promise<boolean> {
  if (typeof window === "undefined") return false;
  const ready = await waitForExtension(
    { type: "ping" },
    (data) => (data.type === "ready" ? true : undefined),
    timeoutMs,
  );
  return ready === true;
}

/** Ask the extension for this browser's ESPN session. Call it from a click
 * handler: the extension only answers right after a user gesture. */
export async function requestEspnCookies(timeoutMs = 6000): Promise<EspnCookies> {
  const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const answer = await waitForExtension(
    { type: "get-espn-cookies", requestId },
    (data) =>
      data.type === "espn-cookies" && data.requestId === requestId ? data : undefined,
    timeoutMs,
  );
  if (!answer) throw new EspnExtensionError("missing");
  if (!answer.ok || !answer.espn_s2 || !answer.swid) {
    const reason = answer.reason as EspnExtensionFailure | undefined;
    throw new EspnExtensionError(reason && reason in FAILURE_MESSAGES ? reason : "error");
  }
  return { espn_s2: answer.espn_s2, swid: normalizeSwid(answer.swid) };
}

/** `{GUID}` — the only shape ESPN accepts. Copies sometimes arrive URL-encoded
 * (%7B…%7D) or without the braces. */
export function normalizeSwid(raw: string): string {
  let value = raw.trim();
  if (/%7B/i.test(value)) {
    try {
      value = decodeURIComponent(value);
    } catch {
      /* leave it for the server to reject */
    }
  }
  const guid = value.replace(/^\{|\}$/g, "");
  return guid ? `{${guid}}` : "";
}

const S2_IN_TEXT = /espn_s2["']?\s*[=:\t]\s*["']?([^\s;"',]+)/i;
const SWID_IN_TEXT =
  /SWID["']?\s*[=:\t]\s*["']?(\{[0-9A-Fa-f-]{32,40}\}|%7B[0-9A-Fa-f-]{32,40}%7D|[0-9A-Fa-f-]{32,40})/i;

/** Pull espn_s2 / SWID out of whatever was pasted: a Cookie header, a "Copy as
 * cURL" command, or rows copied from the browser's cookie table. Returns only
 * what it found, so pasting a bare value still works as a plain field. */
export function parseEspnCookies(text: string): Partial<EspnCookies> {
  const found: Partial<EspnCookies> = {};
  const s2 = S2_IN_TEXT.exec(text);
  if (s2) found.espn_s2 = s2[1];
  const swid = SWID_IN_TEXT.exec(text);
  if (swid) found.swid = normalizeSwid(swid[1]);
  return found;
}

/** A league ID and season from an ESPN league web address — or the ID itself.
 * e.g. https://fantasy.espn.com/football/league?leagueId=12345678&seasonId=2026 */
export function parseEspnLeague(text: string): { leagueId: string; season?: string } {
  const value = text.trim();
  const id = /leagueId=(\d+)/i.exec(value);
  if (!id) return { leagueId: value };
  const season = /seasonId=(\d{4})/i.exec(value);
  return { leagueId: id[1], season: season?.[1] };
}

/** The fantasy season in play: it starts when leagues open in the summer and
 * runs through the January playoffs. */
export function currentFantasySeason(now = new Date()): number {
  return now.getMonth() >= 5 ? now.getFullYear() : now.getFullYear() - 1;
}

/** Where to get the extension: a store listing when one is configured,
 * otherwise the copy bundled with this site. */
export const ESPN_EXTENSION_STORE_URL = process.env.NEXT_PUBLIC_ESPN_EXTENSION_URL || "";
export const ESPN_EXTENSION_ZIP = "/ffai-espn-connect.zip";
