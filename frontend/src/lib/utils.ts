export function injuryColor(status: string | null | undefined): string {
  if (!status) return "bg-green-100 text-green-800";
  const s = status.toLowerCase();
  if (s.includes("out") || s.includes("ir") || s.includes("doubtful"))
    return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";
  if (s.includes("questionable"))
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-green-100 text-green-800";
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
