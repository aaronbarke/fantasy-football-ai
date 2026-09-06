"""Teammate-injury opportunity model.

When a pass-catcher who commands a meaningful share of his team's targets is
*officially out*, those targets don't vanish — they flow to the players behind
him. This module computes, per team, how much vacated target share each
remaining healthy pass-catcher absorbs, so the projection engine can add a
small, capped bump on top of a player's baseline.

Design decisions:

- **Official absences only.** Only Out / Doubtful / IR vacate targets — NOT
  Questionable. Product decision: an uncertain status shouldn't move a
  teammate's number until it's a confirmed sit. See ``_is_absent``.
- **Redistribution weight = recent target share + a depth-chart tilt.** A
  player's own recent target share is the primary signal for who inherits the
  looks (the WR2 behind an injured WR1 already runs the second-most routes), and
  ``depth_chart_order`` breaks ties and gives non-zero weight to backups with no
  target history yet (rookies, early-season slates).
- **No training-camp data.** We deliberately do NOT source training-camp
  first-team reps / camp target rates. That signal lives in beat-reporter
  reports and has no free, structured API (nflverse / Sleeper / ESPN are all
  regular-season only). ``depth_chart_order`` + prior-season ``target_share``,
  both already in our DB, are the accepted quantitative proxies and are what
  this model uses.

The point conversion and the boost cap live in ``projection_service`` (they need
a player's baseline points-per-game); this module stays purely about target
share so it can be unit-tested without touching the projection math.
"""

# An absent player must command at least this much recent target share before
# his absence vacates anything — a deep decoy going out shouldn't move anyone.
MIN_MEANINGFUL_SHARE = 0.08

# An RB only counts as a pass-catcher (able to vacate or absorb pass targets) if
# his recent target share clears this bar — keeps pure goal-line backs out.
RB_PASS_CATCH_MIN = 0.06

# How much a player's depth-chart slot tilts redistribution relative to his raw
# target share. Small on purpose: target share leads, depth chart breaks ties.
DEPTH_WEIGHT = 0.05

PASS_CATCHER_POSITIONS = {"WR", "TE", "RB"}
_ABSENT_STATUSES = {"out", "doubtful", "injured reserve", "ir"}


def _is_absent(status: str | None) -> bool:
    """True for confirmed absences (Out / Doubtful / IR) — never Questionable."""
    if not status:
        return False
    s = status.strip().lower()
    return s in _ABSENT_STATUSES or "injured reserve" in s


def _redistribution_weight(target_share: float, depth_chart_order: int | None) -> float:
    """Weight for how much vacated share a healthy pass-catcher absorbs.

    Recent target share is the main term; a small ``1/depth_chart_order`` tilt
    lets a higher depth-chart slot absorb a bit more and gives backups with no
    target history a non-zero (but small) claim.
    """
    share = target_share or 0.0
    if depth_chart_order and depth_chart_order > 0:
        depth_score = 1.0 / depth_chart_order
    else:
        depth_score = 0.15  # unknown slot → small default so they still absorb a little
    return share + DEPTH_WEIGHT * depth_score


def compute_opportunity_shares(catchers: list[dict]) -> dict[str, dict]:
    """Split each team's vacated target share among its healthy pass-catchers.

    ``catchers`` is one team's pass-catchers, each a dict with keys ``id``,
    ``name``, ``position``, ``target_share`` (recent-season average, may be
    ``None``), ``depth_chart_order`` (may be ``None``) and ``injury_status``.

    Returns ``player_id -> {"extra_share": float, "reason_prefix": str}`` for
    every healthy player who absorbs a positive share. Returns ``{}`` when no
    qualifying teammate is out — so the projection is untouched in the healthy
    case.
    """
    # RBs below the pass-catch bar neither vacate nor absorb pass targets.
    pool = [
        c
        for c in catchers
        if not (c["position"] == "RB" and (c.get("target_share") or 0.0) < RB_PASS_CATCH_MIN)
    ]

    absent = [
        c
        for c in pool
        if _is_absent(c.get("injury_status"))
        and (c.get("target_share") or 0.0) >= MIN_MEANINGFUL_SHARE
    ]
    vacated = sum((c.get("target_share") or 0.0) for c in absent)
    if vacated <= 0:
        return {}

    available = [c for c in pool if not _is_absent(c.get("injury_status"))]
    weights = {c["id"]: _redistribution_weight(c.get("target_share") or 0.0, c.get("depth_chart_order")) for c in available}
    wsum = sum(weights.values())
    if wsum <= 0:
        return {}

    # Name the biggest absence(s) first so the reason reads naturally.
    labels = [
        f"{c['name']} ({c['injury_status']})"
        for c in sorted(absent, key=lambda c: -(c.get("target_share") or 0.0))
    ]
    prefix = ", ".join(labels)

    out: dict[str, dict] = {}
    for c in available:
        share = vacated * weights[c["id"]] / wsum
        if share > 0:
            out[c["id"]] = {"extra_share": share, "reason_prefix": prefix}
    return out
