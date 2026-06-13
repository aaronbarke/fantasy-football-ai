import type { PlayerCard as PlayerCardType } from "@/lib/types";
import InjuryBadge from "./InjuryBadge";
import PlayerAvatar from "./PlayerAvatar";

export default function PlayerCard({
  player,
  slot,
}: {
  player: PlayerCardType;
  slot?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-800">
      <PlayerAvatar
        id={player.id}
        name={player.name}
        position={player.position}
        team={player.team}
        size={38}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{player.name}</p>
        <p className="text-xs text-gray-500">
          {player.position ?? "?"} · {player.team ?? "FA"}
          {slot ? ` · ${slot}` : ""}
        </p>
      </div>
      <InjuryBadge status={player.injury_status} />
    </div>
  );
}
