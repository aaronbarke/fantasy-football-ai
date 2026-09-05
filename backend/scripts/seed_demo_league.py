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

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    LeagueConnection,
    Matchup,
    Player,
    PlayerDraftProfile,
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


async def _top_player_ids(
    db: AsyncSession, position: str, need: int, season: int
) -> list[str]:
    """Highest-ranked players at `position` — ADP-ordered when profiles exist,
    otherwise alphabetical by name so tests without draft profiles still work."""
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

    fallback_q = (
        select(Player.id)
        .where(Player.position == position)
        .order_by(Player.full_name.asc())
        .limit(need + len(ids))
    )
    fallback = (await db.execute(fallback_q)).scalars().all()
    for pid in fallback:
        if pid in ids:
            continue
        ids.append(pid)
        if len(ids) >= need:
            break
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

    team_players: list[list[str]] = [[] for _ in range(NUM_TEAMS)]
    for pos, count in POSITION_COUNTS.items():
        pool = await _top_player_ids(db, pos, NUM_TEAMS * count, settings.current_season)
        for team_idx, ids in enumerate(_snake_distribute(pool, NUM_TEAMS, count)):
            team_players[team_idx].extend(ids)

    starter_count = sum(1 for slot in ROSTER_POSITIONS if slot != "BN")
    for team_idx, players in enumerate(team_players):
        db.add(
            Roster(
                connection_id=conn.id,
                team_id=str(team_idx + 1),
                owner_name=TEAM_NAMES[team_idx],
                players=players,
                starters=players[:starter_count],
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


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    async with SessionLocal() as db:
        await seed_demo_league(db)


if __name__ == "__main__":
    asyncio.run(main())
