/** Traffic-light severity for a game-status string. Only "Active" (or a missing
 * status, which renders no badge anyway) is "healthy" (green); "questionable" is
 * yellow; everything else — Out, Doubtful, IR / Injured Reserve, Suspension, or
 * any unknown designation — is "out" (red). Conservative on purpose: an
 * unrecognized status reads as red rather than a false green. */
export function injurySeverity(
  status: string | null | undefined,
): "out" | "questionable" | "healthy" {
  if (!status) return "healthy";
  const s = status.toLowerCase().trim();
  if (s.includes("questionable")) return "questionable";
  if (s === "active") return "healthy";
  return "out";
}

/** Pill (background + text) classes for a status badge. */
export function injuryColor(status: string | null | undefined): string {
  switch (injurySeverity(status)) {
    case "out":
      return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";
    case "questionable":
      return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
    default:
      return "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300";
  }
}

/** Text-only color classes, for status rendered as inline text (no pill). */
export function injuryTextColor(status: string | null | undefined): string {
  switch (injurySeverity(status)) {
    case "out":
      return "text-red-500 dark:text-red-400";
    case "questionable":
      return "text-amber-500 dark:text-amber-400";
    default:
      return "text-green-600 dark:text-green-400";
  }
}

export function positionColor(position: string | null | undefined): string {
  switch (position) {
    case "QB":
      return "bg-red-500";
    case "RB":
      return "bg-blue-500";
    case "WR":
      return "bg-green-500";
    case "TE":
      return "bg-orange-500";
    case "K":
      return "bg-purple-500";
    case "DEF":
      return "bg-gray-600";
    default:
      return "bg-gray-400";
  }
}

export function formatRecord(wins: number, losses: number, ties: number): string {
  return ties > 0 ? `${wins}-${losses}-${ties}` : `${wins}-${losses}`;
}

/** Human "x ago" from an ISO timestamp. Backend stores naive UTC, so treat a
 * tz-less string as UTC. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const norm = /[Z]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const then = new Date(norm).getTime();
  if (Number.isNaN(then)) return "unknown";
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
