"""Weekly Game Plan — the one-button product moment.

Combines every data source in the app into a single decision package:
projection-optimal lineup, start/sit swaps vs the user's current starters,
win probability against this week's opponent, and the matchup/Vegas context
behind each call. The AI narrative endpoint turns it into a coach's brief.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeagueConnection, Matchup, NflSchedule, Player, Roster
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
# League-average starting K/DEF weekly output in PPR. Rough baseline so the
# matchup preview and gameplan totals include those slots — projecting them
# individually is a fool's errand (K/DST scoring is dominated by touchdown
# variance neither our history nor an external model handles cleanly).
KDEF_BASELINE = 8.0

# A start/sit closer than this is a near-toss-up — we still recommend the higher
# projection, but flag it as close and surface the deciding contextual factor
# (weather, game total, matchup) baked into the projection.
CLOSE_MARGIN = 1.0


def _edge_reason(start: dict, sit: dict) -> str | None:
    """For a close call, the contextual factor most favoring the start."""
    best, best_delta = None, 0.1
    for key, label in (
        ("weather_adj", "weather"),
        ("vegas_adj", "higher team total"),
        ("matchup_adj", "softer matchup"),
    ):
        delta = (start.get(key) or 0) - (sit.get(key) or 0)
        if delta > best_delta:
            best, best_delta = label, delta
    return best


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
        # K/DEF are excluded from the recency-weighted skill-position model in
        # compute_projections — those positions are too noisy for it. Fall back
        # to a flat baseline (league-average starter output) so the matchup
        # preview shows something instead of "No projection", and both sides'
        # totals are comparable when both have a K/DEF slot.
        projected = proj.get("projected")
        if projected is None and p.position in ("K", "DEF"):
            projected = KDEF_BASELINE
        cards.append(
            {
                "id": p.id,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "injury_status": p.injury_status,
                "projected": projected,
                "floor": proj.get("floor"),
                "ceiling": proj.get("ceiling"),
                "confidence": proj.get("confidence"),
                "opponent": (proj.get("components") or {}).get("opponent"),
                "matchup_adj": (proj.get("components") or {}).get("matchup_adj"),
                "vegas_adj": (proj.get("components") or {}).get("vegas_adj"),
                "weather_adj": (proj.get("components") or {}).get("weather_adj"),
                "opportunity_adj": (proj.get("components") or {}).get("opportunity_adj"),
                "boost_reason": proj.get("boost_reason"),
                "defense_injury_adj": (proj.get("components") or {}).get("defense_injury_adj"),
                "defense_reason": proj.get("defense_reason"),
                "external_proj": (proj.get("components") or {}).get("external_proj"),
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


def _all_lineup_slots(conn: LeagueConnection) -> list[str]:
    """The league's full starting lineup in order, including K/DEF (normalized)."""
    raw = [s.upper() for s in (conn.roster_positions or []) if s and s.upper() not in NON_LINEUP]
    slots = ["DEF" if s in {"D/ST", "DST"} else s for s in raw]
    return slots or [*DEFAULT_LINEUP, "K", "DEF"]


def _display_lineup(all_slots: list[str], cards: list[dict]) -> list[dict]:
    """Fill the league's full lineup: skill slots by best projection, K/DEF from
    the roster (no projection). Returns [{slot, player}] in lineup order."""
    from collections import defaultdict, deque

    skill_slots = [s for s in all_slots if s not in {"K", "DEF"}]
    projectable = [c for c in cards if c.get("projected") is not None]
    skill_lineup, _ = optimize_lineup(skill_slots, projectable)

    by_type: dict[str, deque] = defaultdict(deque)
    for entry in skill_lineup:
        by_type[entry["slot"]].append(entry["player"])

    pools: dict[str, deque] = defaultdict(deque)
    for c in cards:
        pos = (c.get("position") or "").upper()
        if pos == "K":
            pools["K"].append(c)
        elif pos in {"DEF", "DST", "D/ST"}:
            pools["DEF"].append(c)

    rows = []
    for s in all_slots:
        pool = pools[s] if s in {"K", "DEF"} else by_type[s]
        rows.append({"slot": s, "player": pool.popleft() if pool else None})
    return rows


async def _matchup_team(
    db: AsyncSession,
    conn: LeagueConnection,
    all_slots: list[str],
    roster: Roster,
    current_points: float | None,
    kickoffs: dict[str, datetime],
    now: datetime,
    live: bool,
) -> dict:
    """Full display lineup, bench (with projections), and both a pre-game
    projected total and a LIVE expected total for one roster.

    Live model: once a starter's NFL game has kicked off, his points are treated
    as already banked in ``current_points`` (the platform's live team score), so
    only starters yet to kick off still carry projection + variance. Before the
    week (or when we have no kickoff times) this collapses to the pure
    projection. K/DEF carry the league-average baseline, no variance."""
    proj = await compute_projections(db, list(roster.players), conn.season)
    cards = await _player_cards(db, list(roster.players), proj)
    rows = _display_lineup(all_slots, cards)
    started_ids = {r["player"]["id"] for r in rows if r["player"]}
    bench = sorted(
        (c for c in cards if c["id"] not in started_ids and c.get("projected") is not None),
        key=lambda c: -(c.get("projected") or 0),
    )

    # Only trust kickoff-based locking once the matchup is actually live (real
    # current points). Otherwise stale/past game times would zero out players.
    use_live = live and current_points is not None
    proj_total = proj_var = 0.0
    remaining = remaining_var = 0.0
    for r in rows:
        p = r["player"]
        if not p or p.get("projected") is None:
            continue
        pts = p["projected"]
        sigma = (proj.get(p["id"]) or {}).get("stdev") or 0.0
        proj_total += pts
        proj_var += sigma**2
        kickoff = kickoffs.get((p.get("team") or "").upper())
        locked = use_live and kickoff is not None and kickoff <= now
        if not locked:
            remaining += pts
            remaining_var += sigma**2

    if use_live:
        expected_total = float(current_points) + remaining
        expected_var = remaining_var
    else:
        expected_total = proj_total
        expected_var = proj_var

    return {
        "rows": rows,
        "bench": bench,
        "team_id": roster.team_id,
        "owner_name": roster.owner_name,
        "record": f"{roster.wins}-{roster.losses}",
        "projected_total": round(proj_total, 1),
        "current_points": round(float(current_points), 1) if current_points is not None else None,
        "expected_total": round(expected_total, 1),
        "_expected_var": expected_var,
    }


async def build_matchup_preview(db: AsyncSession, conn: LeagueConnection) -> dict:
    """Head-to-head scouting report: both lineups aligned slot by slot (the
    league's real lineup, K/DEF included), current + projected scores, each
    team's bench, and a live win probability. Uses the same projection engine as
    the Game Plan."""
    if not conn.team_id:
        return {"status": "no_team"}

    matchups = (
        await db.execute(
            select(Matchup)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.asc())
        )
    ).scalars().all()
    mine = [x for x in matchups if conn.team_id in (x.team_a_id, x.team_b_id)]
    if not mine:
        return {"status": "no_matchup"}
    # The active week is the latest one that has started scoring (live/most
    # recent); before any scores (preseason) it's the earliest upcoming week.
    scored = [x for x in mine if (x.team_a_points or x.team_b_points)]
    m = max(scored, key=lambda x: x.week) if scored else min(mine, key=lambda x: x.week)

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

    user_is_a = m.team_a_id == conn.team_id
    opp_id = m.team_b_id if user_is_a else m.team_a_id
    user_points = m.team_a_points if user_is_a else m.team_b_points
    opp_points = m.team_b_points if user_is_a else m.team_a_points
    user_roster = await _roster(conn.team_id)
    opp_roster = await _roster(opp_id)
    if not (user_roster and user_roster.players and opp_roster and opp_roster.players):
        return {"status": "no_rosters"}

    # Kickoff times for the matchup week, so the live model knows which starters
    # have already played. Empty dict → pure projection (no live info).
    games = (
        await db.execute(
            select(NflSchedule).where(
                NflSchedule.season == conn.season, NflSchedule.week == m.week
            )
        )
    ).scalars().all()
    kickoffs: dict[str, datetime] = {}
    for g in games:
        if g.game_time:
            kickoffs[(g.home_team or "").upper()] = g.game_time
            kickoffs[(g.away_team or "").upper()] = g.game_time
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    live = bool((user_points or 0) or (opp_points or 0))

    all_slots = _all_lineup_slots(conn)
    user = await _matchup_team(db, conn, all_slots, user_roster, user_points, kickoffs, now, live)
    opp = await _matchup_team(db, conn, all_slots, opp_roster, opp_points, kickoffs, now, live)

    # Both lineups are built from the same slot list, so they align index-for-index
    rows = []
    u_rows, o_rows = user.pop("rows"), opp.pop("rows")
    for i in range(max(len(u_rows), len(o_rows))):
        ur = u_rows[i] if i < len(u_rows) else None
        orr = o_rows[i] if i < len(o_rows) else None
        rows.append(
            {
                "slot": (ur or orr)["slot"],
                "user": ur["player"] if ur else None,
                "opponent": orr["player"] if orr else None,
            }
        )

    win_prob = win_probability(
        user["expected_total"], user.pop("_expected_var"),
        opp["expected_total"], opp.pop("_expected_var"),
    )

    return {
        "status": "ok",
        "week": m.week,
        "live": live,
        "win_probability": round(win_prob, 3),
        "user": user,
        "opponent": opp,
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

    # The full league lineup in its configured order, K/DEF included, so the
    # game plan mirrors the matchup preview and the actual roster settings.
    all_slots = _all_lineup_slots(conn)
    lineup = _display_lineup(all_slots, cards)
    used_ids = {r["player"]["id"] for r in lineup if r["player"]}
    bench = sorted(
        (c for c in cards if c["id"] not in used_ids),
        key=lambda c: -(c.get("projected") or 0),
    )

    # Swaps: optimal starters currently on the user's bench. Skill positions
    # only — K/DEF are one-deep, so a start/sit call there is just noise.
    current_starters = set(roster.starters or [])
    swaps = []
    if current_starters:
        optimal_ids = used_ids
        for s in lineup:
            p = s["player"]
            if not p or p["id"] in current_starters:
                continue
            if (p.get("position") or "").upper() in {"K", "DEF", "DST", "D/ST"}:
                continue
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
            # Recommend the higher projection even by a hair; for near
            # toss-ups flag it close and name the contextual tiebreaker.
            gain = None
            close = False
            reason = None
            if displaced is not None:
                gain = round((p.get("projected") or 0) - (displaced.get("projected") or 0), 1)
                close = gain < CLOSE_MARGIN
                if close:
                    reason = _edge_reason(p, displaced)
            swaps.append(
                {
                    "start": p,
                    "sit": displaced,
                    "slot": s["slot"],
                    "gain": gain,
                    "close": close,
                    "reason": reason,
                }
            )

    my_total, my_var = _team_totals(lineup, projections)

    # Opponent projection from this week's matchup, if synced. Prefer the
    # earliest unplayed week — pre-season that's Week 1, mid-season it follows
    # the live week — so the game plan doesn't stubbornly show the final week.
    opponent = None
    matchups = (
        await db.execute(
            select(Matchup)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.asc())
        )
    ).scalars().all()
    mine = [x for x in matchups if conn.team_id in (x.team_a_id, x.team_b_id)]
    unplayed = [x for x in mine if not (x.team_a_points or x.team_b_points)]
    m = unplayed[0] if unplayed else (mine[-1] if mine else None)
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
            opp_lineup = _display_lineup(all_slots, opp_cards)
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
