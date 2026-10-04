/**
 * "How we got this number" — the projection math behind a player's weekly
 * projection, shared by the Game plan and Matchup pages. Mirrors the backend
 * (app/services/projection_service.py):
 *
 *   model     = base + matchup + vegas + weather + teammates out + QB change
 *   projected = s * Sleeper + (1 - s) * model + opposing D injuries
 */

export interface ProjectionTerm {
  label: string;
  value: number;
}

export interface ProjectionBreakdown {
  projected: number | null;
  // Each factor in our model and what it adds (skill players: matchup, Vegas,
  // weather, teammates out, QB change; defenses: opponent offense, defense
  // quality, backup QB, Vegas, weather; kickers: team scoring, dome/weather).
  terms?: ProjectionTerm[] | null;
  base_label?: string | null;
  injury_status?: string | null;
  bye?: boolean;
  base_ppg?: number | null;
  matchup_adj?: number | null;
  vegas_adj?: number | null;
  weather_adj?: number | null;
  opportunity_adj?: number | null;
  qb_adj?: number | null;
  model_proj?: number | null;
  external_proj?: number | null;
  blend_weight?: number | null;
  defense_injury_adj?: number | null;
  boost_reason?: string | null;
  qb_reason?: string | null;
  defense_reason?: string | null;
}

function summaryClass(align: "left" | "right"): string {
  return `cursor-pointer select-none text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 ${
    align === "right" ? "text-right" : ""
  }`;
}

function signed(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}`;
}

/** Expandable "how we got this number" breakdown under a player. */
export default function ProjectionMath({
  p,
  align = "left",
}: {
  p: ProjectionBreakdown;
  align?: "left" | "right";
}) {
  if (p.projected == null || p.bye) return null;
  const status = (p.injury_status ?? "").toLowerCase();
  if (p.projected === 0 && status && status !== "active" && status !== "questionable") {
    return (
      <details className="group mt-2 text-xs">
        <summary className={summaryClass(align)}>
          How we got 0
        </summary>
        <p className="mt-2 rounded-md bg-gray-50 p-2.5 text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
          Ruled out ({p.injury_status}), so he projects 0 this week.
        </p>
      </details>
    );
  }
  const hasModel = p.model_proj != null && p.base_ppg != null;
  const hasSleeper = p.external_proj != null;
  const notes = [p.boost_reason, p.qb_reason, p.defense_reason].filter(
    (n): n is string => !!n,
  );
  if (!hasModel && !hasSleeper && notes.length === 0) return null;

  const terms: [string, number | null | undefined][] = p.terms
    ? p.terms.map((t) => [t.label, t.value])
    : [
        ["Matchup", p.matchup_adj],
        ["Vegas team total", p.vegas_adj],
        ["Weather", p.weather_adj],
        ["Teammates out", p.opportunity_adj],
        ["QB change", p.qb_adj],
      ];
  const s = p.blend_weight ?? (hasModel ? 0 : 1);
  const defense = p.defense_injury_adj ?? 0;

  return (
    <details className="group mt-2 text-xs">
      <summary className={summaryClass(align)}>
        How we got {p.projected}
      </summary>
      <div className="mt-2 space-y-1 rounded-md bg-gray-50 p-2.5 tabular-nums text-gray-600 dark:bg-gray-800/60 dark:text-gray-300">
        {hasModel && (
          <>
            <div className="flex justify-between font-semibold">
              <span>Our model</span>
              <span>{p.model_proj!.toFixed(1)}</span>
            </div>
            <div className="flex justify-between pl-3">
              <span>{p.base_label ?? "Recent-weighted average"}</span>
              <span>{p.base_ppg!.toFixed(1)}</span>
            </div>
            {terms
              .filter(([, v]) => v != null && Math.abs(v) >= 0.05)
              .map(([label, v]) => (
                <div key={label} className="flex justify-between pl-3">
                  <span>{label}</span>
                  <span>{signed(v!)}</span>
                </div>
              ))}
          </>
        )}
        {hasSleeper && (
          <div className="flex justify-between font-semibold">
            <span>Sleeper projection</span>
            <span>{p.external_proj!.toFixed(1)}</span>
          </div>
        )}
        {(hasModel || hasSleeper) && (
        <div className="border-t border-gray-200 pt-1 dark:border-gray-700">
          {hasModel && hasSleeper
            ? `Blend: ${Math.round(s * 100)}% Sleeper + ${Math.round((1 - s) * 100)}% our model` +
              (Math.abs(defense) >= 0.05 ? `, ${signed(defense)} opposing D injuries` : "") +
              ` = ${p.projected}`
            : hasSleeper
              ? `Too little history for our model, so this is Sleeper's number.`
              : `No Sleeper projection, so this is our model` +
                (Math.abs(defense) >= 0.05 ? ` ${signed(defense)} opposing D injuries` : "") +
                "."}
        </div>
        )}
        {notes.map((n) => (
          <p key={n} className="text-gray-500 dark:text-gray-400">
            {n}
          </p>
        ))}
      </div>
    </details>
  );
}
