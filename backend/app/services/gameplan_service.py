"""Weekly Game Plan — the one-button product moment.

Combines every data source in the app into a single decision package:
projection-optimal lineup, start/sit swaps vs the user's current starters,
win probability against this week's opponent, and the matchup/Vegas context
behind each call. The AI narrative endpoint turns it into a coach's brief.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeagueConnection, Matchup, Player, Roster
from app.services.projection_service import compute_projections, win_probability

# Bench/IR-style slots that never take a starter
NON_LINEUP = {"BN", "IR", "TAXI"}
FLEX_ELIGIBLE = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "OP": {"QB", "RB", "WR", "TE"},
}
DEFAULT_LINEUP = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]

# Only surface a start/sit swap when the projected gain clears this — otherwise
# it's noise and the optimizer cries wolf over a fraction of a point.
SWAP_MIN_GAIN = 1.5


def _lineup_slots(conn: LeagueConnection) -> list[str]:
    slots = [
        s for s in (conn.roster_positions or []) if s and s.upper() not in NON_LINEUP
    ]
    # K/DEF have no projections — keep them out of the optimizer
    slots = [s for s in slots if s.upper() not in {"K", "DEF", "D/ST"}]
    return [s.upper() for s in slots] or DEFAULT_LINEUP


def optimize_lineup(
    slots: list[str], players: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Greedy fill: fixed positions first (best projection per slot), then
    flex slots from what's left. Returns (lineup, bench)."""
    pool = sorted(players, key=lambda p: -(p.get("projected") or 0))
    used: set[str] = set()
    lineup: list[dict] = []

    fixed = [s for s in slots if s not in FLEX_ELIGIBLE]
    flexes = [s for s in slots if s in FLEX_ELIGIBLE]

    for slot in fixed:
        pick = next(
            (p for p in pool if p["id"] not in used and p["position"] == slot), None
        )
        lineup.append({"slot": slot, "player": pick})
        if pick:
            used.add(pick["id"])
    for slot in flexes:
        eligible = FLEX_ELIGIBLE[slot]
        pick = next(
            (p for p in pool if p["id"] not in used and p["position"] in eligible),
            None,
        )
        lineup.append({"slot": slot, "player": pick})
        if pick:
            used.add(pick["id"])

    bench = [p for p in pool if p["id"] not in used]
    return lineup, bench


async def _player_cards(
    db: AsyncSession, player_ids: list[str], projections: dict[str, dict]
) -> list[dict]:
    players = (
        (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars().all()
    )
    cards = []
    for p in players:
        proj = projections.get(p.id) or {}
        cards.append(
            {
                "id": p.id,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "injury_status": p.injury_status,
                "projected": proj.get("projected"),
                "floor": proj.get("floor"),
                "ceiling": proj.get("ceiling"),
                "confidence": proj.get("confidence"),
                "opponent": (proj.get("components") or {}).get("opponent"),
                "matchup_adj": (proj.get("components") or {}).get("matchup_adj"),
                "vegas_adj": (proj.get("components") or {}).get("vegas_adj"),
            }
        )
    return cards


def _team_totals(lineup: list[dict], projections: dict[str, dict]) -> tuple[float, float]:
    total = variance = 0.0
    for slot in lineup:
        p = slot.get("player")
        if not p or p.get("projected") is None:
            continue
        total += p["projected"]
        sigma = (projections.get(p["id"]) or {}).get("stdev") or 0.0
        variance += sigma**2
    return total, variance


async def _optimal_for_roster(
    db: AsyncSession, conn: LeagueConnection, slots: list[str], roster: Roster
) -> tuple[list[dict], float, float]:
    """Optimal skill-position lineup + (total, variance) for one roster."""
    proj = await compute_projections(db, list(roster.players), conn.season)
    cards = await _player_cards(db, list(roster.players), proj)
    lineup, _ = optimize_lineup(slots, [c for c in cards if c["projected"] is not None])
    total, variance = _team_totals(lineup, proj)
    return lineup, total, variance


async def build_matchup_preview(db: AsyncSession, conn: LeagueConnection) -> dict:
    """Head-to-head scouting report: both lineups' projections aligned slot by
    slot, projected team totals, and win probability. Uses the same projection
    engine as the Game Plan so the numbers stay consistent across pages."""
    if not conn.team_id:
        return {"status": "no_team"}

    matchups = (
        await db.execute(
            select(Matchup)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.desc())
        )
    ).scalars().all()
    m = next((x for x in matchups if conn.team_id in (x.team_a_id, x.team_b_id)), None)
    if m is None:
        return {"status": "no_matchup"}

    async def _roster(team_id: str | None) -> Roster | None:
        if not team_id:
            return None
        return (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == team_id
                )
            )
        ).scalar_one_or_none()

    opp_id = m.team_b_id if m.team_a_id == conn.team_id else m.team_a_id
    user_roster = await _roster(conn.team_id)
    opp_roster = await _roster(opp_id)
    if not (user_roster and user_roster.players and opp_roster and opp_roster.players):
        return {"status": "no_rosters"}

    slots = _lineup_slots(conn)
    user_lineup, user_total, user_var = await _optimal_for_roster(
        db, conn, slots, user_roster
    )
    opp_lineup, opp_total, opp_var = await _optimal_for_roster(
        db, conn, slots, opp_roster
    )

    # Both lineups are built from the same slot list, so they align index-for-index
    rows = []
    for i in range(max(len(user_lineup), len(opp_lineup))):
        u = user_lineup[i] if i < len(user_lineup) else None
        o = opp_lineup[i] if i < len(opp_lineup) else None
        rows.append(
            {
                "slot": (u or o)["slot"],
                "user": u["player"] if u else None,
                "opponent": o["player"] if o else None,
            }
        )

    return {
        "status": "ok",
        "week": m.week,
        "win_probability": round(
            win_probability(user_total, user_var, opp_total, opp_var), 3
        ),
        "user": {
            "team_id": user_roster.team_id,
            "owner_name": user_roster.owner_name,
            "record": f"{user_roster.wins}-{user_roster.losses}",
            "projected_total": round(user_total, 1),
        },
        "opponent": {
            "team_id": opp_roster.team_id,
            "owner_name": opp_roster.owner_name,
            "record": f"{opp_roster.wins}-{opp_roster.losses}",
            "projected_total": round(opp_total, 1),
        },
        "rows": rows,
    }


async def build_gameplan(db: AsyncSession, conn: LeagueConnection) -> dict:
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == conn.team_id
            )
        )
    ).scalar_one_or_none()
    if roster is None or not roster.players:
        return {"status": "empty_roster"}

    all_ids = list(roster.players)
    projections = await compute_projections(db, all_ids, conn.season)
    cards = await _player_cards(db, all_ids, projections)
    projectable = [c for c in cards if c["projected"] is not None]

    slots = _lineup_slots(conn)
    lineup, bench = optimize_lineup(slots, projectable)

    # Swaps: optimal starters who are currently on the user's bench
    current_starters = set(roster.starters or [])
    swaps = []
    if current_starters:
        optimal_ids = {s["player"]["id"] for s in lineup if s["player"]}
        for s in lineup:
            p = s["player"]
            if p and p["id"] not in current_starters:
                # Find the currently-started player at this position being displaced
                displaced = next(
                    (
                        c
                        for c in projectable
                        if c["id"] in current_starters
                        and c["id"] not in optimal_ids
                        and c["position"] == p["position"]
                    ),
                    None,
                )
                # Skip trivial swaps: a sub-1.5pt edge over the current starter
                # isn't worth flagging. (Filling an empty slot always counts.)
                gain = None
                if displaced is not None:
                    gain = round((p.get("projected") or 0) - (displaced.get("projected") or 0), 1)
                    if gain < SWAP_MIN_GAIN:
                        continue
                swaps.append({"start": p, "sit": displaced, "slot": s["slot"], "gain": gain})

    my_total, my_var = _team_totals(lineup, projections)

    # Opponent projection from this week's matchup, if synced
    opponent = None
    matchups = (
        await db.execute(
            select(Matchup)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.desc())
        )
    ).scalars().all()
    m = next(
        (x for x in matchups if conn.team_id in (x.team_a_id, x.team_b_id)), None
    )
    if m:
        opp_id = m.team_b_id if m.team_a_id == conn.team_id else m.team_a_id
        opp_roster = (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == opp_id
                )
            )
        ).scalar_one_or_none()
        if opp_roster and opp_roster.players:
            opp_proj = await compute_projections(db, list(opp_roster.players), conn.season)
            opp_cards = await _player_cards(db, list(opp_roster.players), opp_proj)
            opp_lineup, _ = optimize_lineup(
                slots, [c for c in opp_cards if c["projected"] is not None]
            )
            opp_total, opp_var = _team_totals(opp_lineup, opp_proj)
            opponent = {
                "name": opp_roster.owner_name,
                "projected_total": round(opp_total, 1),
                "win_probability": round(
                    win_probability(my_total, my_var, opp_total, opp_var), 3
                ),
                "week": m.week,
            }

    return {
        "status": "ok",
        "projected_total": round(my_total, 1),
        "lineup": lineup,
        "bench": bench[:10],
        "swaps": swaps,
        "opponent": opponent,
        "stats_basis": "Two-season blend, matchup + Vegas adjusted",
    }
