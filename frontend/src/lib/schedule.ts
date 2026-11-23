export interface MatchupCell {
  week: number;
  opponent: string | null;
  home?: boolean;
  rank: number | null;
  pts_allowed_avg?: number | null;
}

export function cellColor(rank: number | null): string {
  // Green/gray pick up their dark-mode tints from the global remap layer; the
  // warm tiers need explicit dark variants or they glow cream on the dark theme.
  if (rank == null) return "bg-gray-100 text-gray-400";
  if (rank <= 8) return "bg-green-100 text-green-800";
  if (rank <= 16) return "bg-green-50 text-green-700";
  if (rank <= 24)
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";
}

/** Hover text explaining what a matchup cell's rank means for a position. */
export function matchupTitle(
  position: string | null,
  c: MatchupCell,
): string | undefined {
  if (c.pts_allowed_avg == null || !c.opponent) return undefined;
  if (position === "DEF")
    return `Defenses average ~${c.pts_allowed_avg} fantasy pts vs ${c.opponent}'s offense (rank ${c.rank}/32)`;
  if (position === "K")
    return `${c.opponent} allows ${c.pts_allowed_avg} points/gm (rank ${c.rank}/32 for kickers)`;
  return `${c.opponent} allows ${c.pts_allowed_avg} fantasy pts/gm to ${position}s (rank ${c.rank}/32)`;
}
