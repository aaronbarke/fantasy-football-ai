"use client";

import { useState } from "react";
import { User } from "lucide-react";

const DEF = new Set(["DEF", "DST", "D/ST"]);

/** Player headshot from the Sleeper CDN (IDs are Sleeper IDs), team logo for
 * defenses, and a neutral silhouette when no image exists or it fails to load. */
export default function PlayerAvatar({
  id,
  name,
  position,
  team,
  size = 36,
}: {
  id?: string | null;
  name?: string | null;
  position?: string | null;
  team?: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const isDef = position ? DEF.has(position.toUpperCase()) : false;
  const src = isDef
    ? team
      ? `https://a.espncdn.com/i/teamlogos/nfl/500/${team.toLowerCase()}.png`
      : null
    : id
      ? `https://sleepercdn.com/content/nfl/players/thumb/${id}.jpg`
      : null;

  const dim = { width: size, height: size };

  if (!src || failed) {
    return (
      <div
        style={dim}
        aria-label={name ?? "player"}
        className="flex shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500"
      >
        <User style={{ width: size * 0.5, height: size * 0.5 }} />
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={name ?? ""}
      width={size}
      height={size}
      style={dim}
      loading="lazy"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-full bg-gray-100 dark:bg-gray-800 ${
        isDef ? "object-contain p-1" : "object-cover object-top"
      }`}
    />
  );
}
