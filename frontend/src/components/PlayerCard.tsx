import type { PlayerCard as PlayerCardType } from "@/lib/types";
import { positionColor } from "@/lib/utils";
import InjuryBadge from "./InjuryBadge";

export default function PlayerCard({
  player,
  slot,
}: {
  player: PlayerCardType;
  slot?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3">
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-xs font-bold text-white ${positionColor(player.position)}`}
      >
        {player.position ?? "?"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{player.name}</p>
        <p className="text-xs text-gray-500">
          {player.team ?? "FA"}
          {slot ? ` · ${slot}` : ""}
        </p>
      </div>
      <InjuryBadge status={player.injury_status} />
    </div>
  );
}
