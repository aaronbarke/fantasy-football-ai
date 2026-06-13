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
