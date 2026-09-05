"""Seed the shared demo account with a canned 10-team fixture league.

The public demo login must not expose real users' rosters or leaguemate
names, so we hand-build a fake league instead of cloning someone real. Team
names are neutral / stats-flavored; owner names are left blank. Rosters are
filled from real rows in the `players` table so the app renders real names,
positions, projections, and injury status — only the league metadata is
fabricated.

Idempotent: safe to re-run. If the demo user already has a league, this is
a no-op.

Run:  python -m scripts.seed_demo_league
"""

import argparse
import asyncio
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AvailablePlayer,
    LeagueConnection,
    Matchup,
    Player,
    PlayerDraftProfile,
    PlayerStatsWeekly,
    Roster,
    User,
)
from app.utils.security import DEMO_EMAIL, hash_password

logger = logging.getLogger(__name__)

# Neutral stats-flavored labels — no real people. Rendered as "team name" in
# the app (the UI reads owner_name as the team identifier).
TEAM_NAMES = [
    "Model Behavior",
    "The Regressors",
    "Standard Deviants",
    "P-Value Wranglers",
    "Bayesian Boys",
    "Overfit Boys",
    "Chi-Squared Choppers",
    "The Optimizers",
    "Confidence Interval FC",
    "Portfolio FC",  # the demo user's own team
]
NUM_TEAMS = 10
DEMO_TEAM_ID = str(NUM_TEAMS)  # last team in TEAM_NAMES
DEMO_LEAGUE_ID = "demo-league"

ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF",
    "BN", "BN", "BN", "BN", "BN", "BN",
]

# Per-team positional composition — sums to 15 to fill ROSTER_POSITIONS.
POSITION_COUNTS = {"QB": 2, "RB": 4, "WR": 5, "TE": 2, "K": 1, "DEF": 1}

# The nine starting slots (ROSTER_POSITIONS minus the bench) and what the FLEX
# can hold. Used to seat each team's best player per slot as its starters.
STARTER_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
FLEX_ELIGIBLE = ("RB", "WR", "TE")


def _fill_starters(by_pos: dict[str, list[str]]) -> list[str]:
    """Seat a starting lineup from a team's players, best available per slot.

    `by_pos` maps position -> player ids (best first). Fixed slots take the top
    unused player at their position; FLEX takes the best unused RB/WR/TE."""
    used: set[str] = set()
    starters: list[str] = []
    for slot in STARTER_SLOTS:
        positions = FLEX_ELIGIBLE if slot == "FLEX" else (slot,)
        pick = next(
            (pid for pos in positions for pid in by_pos.get(pos, []) if pid not in used),
            None,
        )
        if pick is not None:
            used.add(pick)
            starters.append(pick)
    return starters


async def _extend_unique(ids: list[str], candidates, need: int) -> None:
    """Append candidate ids not already present, until `need` is reached."""
    for pid in candidates:
        if pid in ids:
            continue
        ids.append(pid)
        if len(ids) >= need:
            return


async def _top_player_ids(
    db: AsyncSession, position: str, need: int, season: int
) -> list[str]:
    """The `need` best players at `position`, in this preference order:

    1. **ADP** when draft profiles exist (the sharpest ordering).
    2. **Recent fantasy production** otherwise — total PPR points across the
       seasons already in `player_stats_weekly`. This is what makes the demo
       roster look real: it picks players who actually scored, so they have
       projections instead of the alphabetical filler the old fallback gave.
    3. **Alphabetical** as a last resort, so tests with neither ADP nor stats
       still fill a roster.
    """
    ranked = (
        (
            await db.execute(
                select(Player.id)
                .join(
                    PlayerDraftProfile,
                    (PlayerDraftProfile.player_id == Player.id)
                    & (PlayerDraftProfile.season == season)
                    & (PlayerDraftProfile.scoring == "ppr"),
                )
                .where(Player.position == position)
                .where(PlayerDraftProfile.adp_consensus.isnot(None))
                .order_by(PlayerDraftProfile.adp_consensus.asc())
                .limit(need)
            )
        )
        .scalars()
        .all()
    )
    ids = list(ranked)
    if len(ids) >= need:
        return ids

    by_production = (
        (
            await db.execute(
                select(Player.id)
                .join(PlayerStatsWeekly, PlayerStatsWeekly.player_id == Player.id)
                .where(Player.position == position)
                .group_by(Player.id)
                .order_by(func.sum(PlayerStatsWeekly.fantasy_points_ppr).desc())
                .limit(need + len(ids))
            )
        )
        .scalars()
        .all()
    )
    await _extend_unique(ids, by_production, need)
    if len(ids) >= need:
        return ids

    alphabetical = (
        (
            await db.execute(
                select(Player.id)
                .where(Player.position == position)
                .order_by(Player.full_name.asc())
                .limit(need + len(ids))
            )
        )
        .scalars()
        .all()
    )
    await _extend_unique(ids, alphabetical, need)
    return ids


def _snake_distribute(pool: list[str], teams: int, per_team: int) -> list[list[str]]:
    """Distribute `pool` across `teams` in snake order (1..N, N..1, 1..N, …)."""
    out: list[list[str]] = [[] for _ in range(teams)]
    idx = 0
    for round_no in range(per_team):
        order = range(teams) if round_no % 2 == 0 else range(teams - 1, -1, -1)
        for t in order:
            if idx >= len(pool):
                return out
            out[t].append(pool[idx])
            idx += 1
    return out


async def _get_or_create_demo_user(db: AsyncSession) -> User:
    user = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    if user is not None:
        return user
    # Demo signs in via /api/auth/demo, so the hash is intentionally unusable.
    import secrets

    user = User(email=DEMO_EMAIL, password_hash=hash_password(secrets.token_urlsafe(32)))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def reset_demo_league(db: AsyncSession) -> int:
    """Delete the demo user's existing league(s) and their child rows.

    Needed when the demo account was populated by the old clone-from-real-user
    flow (or an earlier fixture) and we want to re-seed from scratch. No-op if
    the demo user or its leagues don't exist. Returns the number of league
    connections removed."""
    demo = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    if demo is None:
        return 0

    conn_ids = (
        (
            await db.execute(
                select(LeagueConnection.id).where(LeagueConnection.user_id == demo.id)
            )
        )
        .scalars()
        .all()
    )
    if not conn_ids:
        return 0

    # Delete children first so this works whether or not the FKs cascade.
    for model in (Roster, Matchup, AvailablePlayer):
        await db.execute(delete(model).where(model.connection_id.in_(conn_ids)))
    await db.execute(delete(LeagueConnection).where(LeagueConnection.id.in_(conn_ids)))
    await db.commit()
    logger.info("Reset demo league: removed %d connection(s).", len(conn_ids))
    return len(conn_ids)


async def seed_demo_league(db: AsyncSession) -> bool:
    """Populate the demo user's league from the canned fixture.

    Returns True when a new league was written, False on the idempotent no-op
    (demo user already has one)."""
    settings = get_settings()
    demo = await _get_or_create_demo_user(db)

    existing = (
        await db.execute(
            select(LeagueConnection.id).where(LeagueConnection.user_id == demo.id)
        )
    ).first()
    if existing:
        logger.info("Demo user already has a league — skipping seed.")
        return False

    conn = LeagueConnection(
        user_id=demo.id,
        platform="sleeper",
        platform_user_id=None,
        league_id=DEMO_LEAGUE_ID,
        league_name="Portfolio Demo League",
        season=settings.current_season,
        scoring_type="ppr",
        scoring_settings={"rec": 1.0},
        roster_positions=ROSTER_POSITIONS,
        credentials=None,
        team_id=DEMO_TEAM_ID,
    )
    db.add(conn)
    await db.flush()  # assign conn.id

    # Deal players out by position: team_by_pos[team][pos] holds that team's
    # players at each position, best first (snake order keeps it fair).
    team_by_pos: list[dict[str, list[str]]] = [
        {pos: [] for pos in POSITION_COUNTS} for _ in range(NUM_TEAMS)
    ]
    for pos, count in POSITION_COUNTS.items():
        pool = await _top_player_ids(db, pos, NUM_TEAMS * count, settings.current_season)
        for team_idx, ids in enumerate(_snake_distribute(pool, NUM_TEAMS, count)):
            team_by_pos[team_idx][pos] = list(ids)

    for team_idx in range(NUM_TEAMS):
        by_pos = {pos: list(ids) for pos, ids in team_by_pos[team_idx].items()}
        starters = _fill_starters(by_pos)
        # Full roster = starters, then everyone left over on the bench.
        bench = [
            pid
            for pos in POSITION_COUNTS
            for pid in team_by_pos[team_idx][pos]
            if pid not in starters
        ]
        db.add(
            Roster(
                connection_id=conn.id,
                team_id=str(team_idx + 1),
                owner_name=TEAM_NAMES[team_idx],
                players=starters + bench,
                starters=starters,
                wins=0,
                losses=0,
                ties=0,
                points_for=0,
                points_against=0,
            )
        )

    # One week of round-robin pairings, zeroed out so the app treats it as an
    # upcoming week rather than a completed one.
    for a in range(1, NUM_TEAMS, 2):
        db.add(
            Matchup(
                connection_id=conn.id,
                week=1,
                team_a_id=str(a),
                team_b_id=str(a + 1),
                team_a_points=0,
                team_b_points=0,
            )
        )
    await db.commit()
    logger.info("Seeded demo league: %d rosters, 1 week of matchups.", NUM_TEAMS)
    return True


async def main(reset: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    async with SessionLocal() as db:
        if reset:
            await reset_demo_league(db)
        await seed_demo_league(db)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the shared demo league.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the demo user's existing league first, then re-seed from "
        "the fixture (use this to replace an old clone-from-real-user league).",
    )
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset))
