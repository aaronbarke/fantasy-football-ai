"""Weekly Game Plan — the one-button product moment.

Combines every data source in the app into a single decision package:
projection-optimal lineup, start/sit swaps vs the user's current starters,
win probability against this week's opponent, and the matchup/Vegas context
behind each call. The AI narrative endpoint turns it into a coach's brief.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    LeagueConnection,
    LivePlayerScore,
    Matchup,
    MatchupOdds,
    NflSchedule,
    Player,
    Roster,
)
from app.services.projection_service import compute_projections, win_probability
from app.services.schedule_service import current_nfl_week

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

# Real length of an NFL game (kickoff to final whistle), used to estimate how
# much of an in-progress game — and so of a player's projection — is still left.
GAME_MINUTES = 190.0


def _remaining_fraction(kickoff: datetime | None, now: datetime) -> float:
    """Share of a player's game still to be played: 1 before kickoff, falling
    linearly to 0 by the final whistle. Unknown kickoff → treat as unplayed."""
    if kickoff is None or kickoff > now:
        return 1.0
    elapsed = (now - kickoff).total_seconds() / 60.0
    return max(0.0, 1.0 - elapsed / GAME_MINUTES)


def _record(roster: Roster) -> str:
    base = f"{roster.wins}-{roster.losses}"
    return f"{base}-{roster.ties}" if roster.ties else base


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
        # compute_projections covers K/DEF (flat kicker baseline, matchup-driven
        # DEF), including zeroing them on a bye. This fallback only applies if a
        # K/DEF somehow comes back without a projection, so both sides' totals
        # stay comparable instead of showing "No projection".
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
                "bye": bool(proj.get("bye")),
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


# Canonical display order: skill positions, then FLEX, then DEF, and K last.
_SLOT_DISPLAY_ORDER = {
    "QB": 0, "RB": 1, "WR": 2, "TE": 3,
    "FLEX": 4, "WRRB_FLEX": 4, "REC_FLEX": 4, "SUPER_FLEX": 4, "OP": 4,
    "DEF": 5, "K": 6,
}


def _all_lineup_slots(conn: LeagueConnection) -> list[str]:
    """The league's full starting lineup, K/DEF included and normalized, in a
    consistent display order (skill → FLEX → DEF → K)."""
    raw = [s.upper() for s in (conn.roster_positions or []) if s and s.upper() not in NON_LINEUP]
    slots = ["DEF" if s in {"D/ST", "DST"} else s for s in raw]
    slots = slots or [*DEFAULT_LINEUP, "K", "DEF"]
    return sorted(slots, key=lambda s: _SLOT_DISPLAY_ORDER.get(s, 4))


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

    # Fill K/DEF slots best-projection first, so the optimal streamer starts
    # (a defense with a great matchup should beat the one you happen to roster).
    def _by_proj(pos_set: set[str]) -> deque:
        pool = [c for c in cards if (c.get("position") or "").upper() in pos_set]
        pool.sort(key=lambda c: -(c.get("projected") or 0))
        return deque(pool)

    pools: dict[str, deque] = {
        "K": _by_proj({"K"}),
        "DEF": _by_proj({"DEF", "DST", "D/ST"}),
    }

    rows = []
    for s in all_slots:
        pool = pools[s] if s in {"K", "DEF"} else by_type[s]
        rows.append({"slot": s, "player": pool.popleft() if pool else None})
    return rows


def _actual_lineup(all_slots: list[str], cards: list[dict], starter_ids: list[str]) -> list[dict]:
    """The manager's ACTUAL starting lineup (who they really set), mapped to
    slots by position — not the projection-optimal lineup. This is what the
    matchup should show: a benched player (e.g. one sitting because he's Out)
    must NOT appear as a starter."""
    by_id = {c["id"]: c for c in cards}
    pool = [by_id[sid] for sid in starter_ids if sid in by_id]
    used: set[str] = set()

    def pos(c: dict) -> str:
        return (c.get("position") or "").upper()

    def _fixed_match(slot: str, c: dict) -> bool:
        if slot in {"DEF", "DST", "D/ST"}:
            return pos(c) in {"DEF", "DST", "D/ST"}
        return pos(c) == slot

    assigned: dict[int, dict] = {}
    # Fixed positions (incl. K/DEF) first, then flex from whoever's left — so a
    # flex slot can't steal a player a dedicated slot needs.
    for i, slot in enumerate(all_slots):
        if slot in FLEX_ELIGIBLE:
            continue
        c = next((x for x in pool if x["id"] not in used and _fixed_match(slot, x)), None)
        if c:
            used.add(c["id"])
            assigned[i] = c
    for i, slot in enumerate(all_slots):
        if slot not in FLEX_ELIGIBLE:
            continue
        eligible = FLEX_ELIGIBLE[slot]
        c = next((x for x in pool if x["id"] not in used and pos(x) in eligible), None)
        if c:
            used.add(c["id"])
            assigned[i] = c
    return [{"slot": slot, "player": assigned.get(i)} for i, slot in enumerate(all_slots)]


async def _matchup_team(
    db: AsyncSession,
    conn: LeagueConnection,
    all_slots: list[str],
    roster: Roster,
    current_points: float | None,
    kickoffs: dict[str, datetime],
    now: datetime,
    live: bool,
    optimal: bool,
    live_scores: dict[str, float],
) -> dict:
    """Full display lineup, bench (with projections), and both a pre-game
    projected total and a LIVE expected total for one roster.

    ``optimal`` picks the pre-game lineup: the user's side shows the
    projection-optimal lineup (what they SHOULD start), while the opponent shows
    the lineup they ACTUALLY set. Once games are live, both sides show the
    lineup actually set — that's the lineup the platform is scoring, so it's the
    only one whose players' points add up to ``current_points``.

    Live model: ``current_points`` (the platform's live team score) already
    banks everything scored so far, so each starter adds only the share of his
    projection still to be played — all of it before kickoff, a shrinking share
    while his game is on, none once it's final. Variance shrinks the same way.
    Before the week (or with no kickoff times) this is the pure projection."""
    scoring = conn.scoring_type or "ppr"
    proj = await compute_projections(db, list(roster.players), conn.season, scoring)
    cards = await _player_cards(db, list(roster.players), proj)
    for c in cards:
        c["actual_points"] = live_scores.get(c["id"])

    # Only trust kickoff-based locking once the matchup is actually live (real
    # current points). Otherwise stale/past game times would zero out players.
    use_live = live and current_points is not None
    starters = list(roster.starters or [])
    if starters and (use_live or not optimal):
        rows = _actual_lineup(all_slots, cards, starters)
    else:
        rows = _display_lineup(all_slots, cards)
    started_ids = {r["player"]["id"] for r in rows if r["player"]}
    bench = sorted(
        (c for c in cards if c["id"] not in started_ids and c.get("projected") is not None),
        key=lambda c: -(c.get("projected") or 0),
    )

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
        left = (
            _remaining_fraction(kickoffs.get((p.get("team") or "").upper()), now)
            if use_live
            else 1.0
        )
        remaining += pts * left
        remaining_var += (sigma**2) * left

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
        "record": _record(roster),
        "projected_total": round(proj_total, 1),
        "current_points": round(float(current_points), 1) if current_points is not None else None,
        "expected_total": round(expected_total, 1),
        "_expected_var": expected_var,
    }


async def _current_nfl_week(db: AsyncSession, season: int, now: datetime) -> int | None:
    """The active NFL week from the schedule (see schedule_service)."""
    return await current_nfl_week(db, season, now)


async def resolve_current_matchup(
    db: AsyncSession, conn: LeagueConnection, now: datetime | None = None
) -> Matchup | None:
    """The user's matchup for the current NFL week — the one definition of
    "this week" shared by the matchup page, dashboard, game plan and chat.

    Week comes from the NFL schedule, never from which scores happen to be zero
    (a live week has points on the board, which used to flip everything to next
    week's opponent mid-Sunday). If that week isn't synced yet, use the nearest
    earlier week we have. With no schedule loaded, fall back to the earliest
    week the user's matchup hasn't started, else the latest one."""
    if not conn.team_id:
        return None
    matchups = (
        await db.execute(
            select(Matchup)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.asc())
        )
    ).scalars().all()
    mine = [x for x in matchups if conn.team_id in (x.team_a_id, x.team_b_id)]
    if not mine:
        return None

    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    by_week = {x.week: x for x in mine}
    current_week = await current_nfl_week(db, conn.season, now)
    if current_week is not None:
        if current_week in by_week:
            return by_week[current_week]
        at_or_below = [w for w in by_week if w <= current_week]
        return by_week[max(at_or_below)] if at_or_below else by_week[min(by_week)]
    unplayed = [x for x in mine if not (x.team_a_points or x.team_b_points)]
    return unplayed[0] if unplayed else mine[-1]


async def build_matchup_preview(db: AsyncSession, conn: LeagueConnection) -> dict:
    """Head-to-head scouting report: both lineups aligned slot by slot (the
    league's real lineup, K/DEF included), current + projected scores, each
    team's bench, and a live win probability. Uses the same projection engine as
    the Game Plan."""
    if not conn.team_id:
        return {"status": "no_team"}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    m = await resolve_current_matchup(db, conn, now)
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
    live = bool((user_points or 0) or (opp_points or 0))

    live_score_rows = (
        await db.execute(
            select(LivePlayerScore.player_id, LivePlayerScore.points).where(
                LivePlayerScore.connection_id == conn.id, LivePlayerScore.week == m.week
            )
        )
    ).all()
    live_scores = {pid: float(pts) for pid, pts in live_score_rows}

    all_slots = _all_lineup_slots(conn)
    # Your side: the optimal lineup (what you should start). Opponent: what they
    # actually set — you're stuck playing whoever they benched or started.
    user = await _matchup_team(db, conn, all_slots, user_roster, user_points, kickoffs, now, live, True, live_scores)
    opp = await _matchup_team(db, conn, all_slots, opp_roster, opp_points, kickoffs, now, live, False, live_scores)

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

    # Snapshot the live odds so the page can chart how they moved during games.
    if live:
        await _record_odds_snapshot(db, conn, m.week, win_prob, user_points, opp_points)

    return {
        "status": "ok",
        "week": m.week,
        "live": live,
        "win_probability": round(win_prob, 3),
        "user": user,
        "opponent": opp,
        "rows": rows,
    }


async def _record_odds_snapshot(
    db: AsyncSession,
    conn: LeagueConnection,
    week: int,
    win_prob: float,
    user_points: float | None,
    opp_points: float | None,
) -> None:
    """Append a win-probability point, but only when it actually moved (score or
    odds changed) — so the timeline is meaningful and writes stay bounded."""
    last = (
        await db.execute(
            select(MatchupOdds)
            .where(MatchupOdds.connection_id == conn.id, MatchupOdds.week == week)
            .order_by(MatchupOdds.captured_at.desc(), MatchupOdds.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    up, op = float(user_points or 0), float(opp_points or 0)
    if (
        last is not None
        and round(last.win_probability, 4) == round(win_prob, 4)
        and float(last.user_points or 0) == up
        and float(last.opp_points or 0) == op
    ):
        return
    db.add(
        MatchupOdds(
            connection_id=conn.id,
            week=week,
            win_probability=round(win_prob, 4),
            user_points=up,
            opp_points=op,
        )
    )
    await db.commit()


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

    scoring = conn.scoring_type or "ppr"
    all_ids = list(roster.players)
    projections = await compute_projections(db, all_ids, conn.season, scoring)
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

    # Swaps: every optimal starter the user isn't currently starting, paired
    # with the current starter he should replace. Each benched-for player is
    # used once — same position first, else anyone eligible for that slot (a
    # FLEX upgrade can send a WR to the bench for an RB). Kicker start/sit is
    # noise, but DEF has a real matchup projection, so streaming calls count.
    current_starters = set(roster.starters or [])
    swaps = []
    if current_starters:
        outgoing = [
            c for c in projectable
            if c["id"] in current_starters and c["id"] not in used_ids
        ]
        paired: set[str] = set()
        for s in lineup:
            p = s["player"]
            if not p or p["id"] in current_starters:
                continue
            if (p.get("position") or "").upper() == "K":
                continue
            eligible = FLEX_ELIGIBLE.get(s["slot"], {p["position"]})
            open_out = [c for c in outgoing if c["id"] not in paired]
            displaced = next(
                (c for c in open_out if c["position"] == p["position"]), None
            ) or next((c for c in open_out if c["position"] in eligible), None)
            # Recommend the higher projection even by a hair; for near
            # toss-ups flag it close and name the contextual tiebreaker.
            gain = None
            close = False
            reason = None
            if displaced is not None:
                paired.add(displaced["id"])
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

    # Opponent projection for the current NFL week's matchup — the same week
    # the matchup page shows, resolved from the schedule, not from which
    # scores are still zero.
    opponent = None
    m = await resolve_current_matchup(db, conn)
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
            opp_proj = await compute_projections(
                db, list(opp_roster.players), conn.season, scoring
            )
            opp_cards = await _player_cards(db, list(opp_roster.players), opp_proj)
            # You play the lineup they actually set, like the matchup page.
            opp_lineup = (
                _actual_lineup(all_slots, opp_cards, list(opp_roster.starters))
                if opp_roster.starters
                else _display_lineup(all_slots, opp_cards)
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
