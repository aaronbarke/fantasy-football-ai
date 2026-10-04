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

- **Carries too.** A running back's absence vacates his share of the team's RB
  carries, which flows to the healthy backs (by their own carry share, with the
  same depth-chart tilt) — the committee back behind an injured starter is the
  classic case.
- **Fresh absences only.** A player who has already missed the last few games
  is baked into his teammates' recent numbers, so his vacated share fades out
  (``freshness``): full if he played in one of the last two weeks of data, half
  if within four, nothing after that. Otherwise a season-long IR stint would
  boost the same teammates every single week.

The point conversion and the boost cap live in ``projection_service`` (they need
a player's baseline points-per-game); this module stays purely about shares so
it can be unit-tested without touching the projection math.
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

# An absent RB must have had at least this share of his team's RB carries to
# vacate any — a third-stringer going out shouldn't move the starter.
MIN_MEANINGFUL_RUSH_SHARE = 0.20
# Depth tilt for carries: bigger than for targets, because the next man up on
# the depth chart really does inherit the work even with little history.
RUSH_DEPTH_WEIGHT = 0.10

PASS_CATCHER_POSITIONS = {"WR", "TE", "RB"}
# Sleeper and ESPN spell these differently ("IR" vs "Injured Reserve", "Sus" vs
# "Suspension"), so both spellings are listed. PUP / NFI / suspended players
# aren't eligible to play at all, which makes them as absent as IR.
_ABSENT_STATUSES = {
    "out", "doubtful", "injured reserve", "ir",
    "sus", "susp", "suspended", "suspension",
    "pup", "pup-r", "pup-p", "physically unable to perform",
    "nfi", "nfi-r", "nfi-a", "non-football injury",
}
# Absences that last weeks, not days — a trade or rest-of-season view should
# treat these players as unavailable (a one-week "Out" shouldn't).
_LONG_TERM_STATUSES = _ABSENT_STATUSES - {"out", "doubtful"}


def _is_absent(status: str | None) -> bool:
    """True for confirmed absences (Out / Doubtful / IR / PUP / suspended) —
    never Questionable."""
    if not status:
        return False
    s = status.strip().lower()
    return s in _ABSENT_STATUSES or "injured reserve" in s


def is_long_term_absent(status: str | None) -> bool:
    """IR / PUP / NFI / suspension — out for weeks, not just this game."""
    if not status:
        return False
    s = status.strip().lower()
    return s in _LONG_TERM_STATUSES or "injured reserve" in s


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


def absence_freshness(
    last_game: tuple[int, int] | None, latest: tuple[int, int] | None
) -> float:
    """How much of an absent player's share is still "vacated" news.

    ``last_game`` is his most recent (season, week) with stats; ``latest`` is
    the most recent (season, week) of anyone's stats. 1.0 if he played in one
    of the last two weeks of data (a bye in between is fine), 0.5 within four,
    0.0 beyond — by then his teammates' recent games already show the extra
    work. No data to judge → 1.0."""
    if latest is None or last_game is None:
        return 1.0
    season, week = latest
    last_season, last_week = last_game
    if last_season == season:
        missed = week - last_week
    elif last_season == season - 1:
        missed = week + 1  # sat out every game so far this season
    else:
        return 0.0
    if missed <= 1:
        return 1.0
    if missed <= 3:
        return 0.5
    return 0.0


def compute_rush_shares(rbs: list[dict]) -> dict[str, dict]:
    """Split each team's vacated RB carries among its healthy backs.

    ``rbs`` is one team's running backs, each a dict with ``id``, ``name``,
    ``rush_share`` (share of the team's RB carries), ``depth_chart_order``,
    ``injury_status`` and optional ``freshness`` (see ``absence_freshness``).
    Returns ``player_id -> {"extra_share", "reason_prefix"}``; ``{}`` when no
    qualifying back is out."""
    absent = [
        r for r in rbs
        if _is_absent(r.get("injury_status"))
        and (r.get("rush_share") or 0.0) >= MIN_MEANINGFUL_RUSH_SHARE
        and r.get("freshness", 1.0) > 0
    ]
    vacated = sum((r.get("rush_share") or 0.0) * r.get("freshness", 1.0) for r in absent)
    if vacated <= 0:
        return {}
    available = [r for r in rbs if not _is_absent(r.get("injury_status"))]
    weights = {}
    for r in available:
        depth = r.get("depth_chart_order")
        depth_score = 1.0 / depth if depth and depth > 0 else 0.15
        weights[r["id"]] = (r.get("rush_share") or 0.0) + RUSH_DEPTH_WEIGHT * depth_score
    wsum = sum(weights.values())
    if wsum <= 0:
        return {}
    prefix = ", ".join(
        f"{r['name']} ({r['injury_status']})"
        for r in sorted(absent, key=lambda r: -(r.get("rush_share") or 0.0))
    )
    return {
        r["id"]: {"extra_share": vacated * weights[r["id"]] / wsum, "reason_prefix": prefix}
        for r in available
        if weights[r["id"]] > 0
    }


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
        and c.get("freshness", 1.0) > 0
    ]
    vacated = sum((c.get("target_share") or 0.0) * c.get("freshness", 1.0) for c in absent)
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
