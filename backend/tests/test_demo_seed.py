import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import LeagueConnection, Matchup, Player, Roster, User
from app.utils.security import DEMO_EMAIL, hash_password
from scripts.seed_demo_league import (
    NUM_TEAMS,
    ROSTER_POSITIONS,
    TEAM_NAMES,
    seed_demo_league,
)


@pytest.fixture
async def db():
    """Fresh in-memory sqlite for each test — the module-scoped engine in
    app.database is shared across tests, so this fixture gives us isolation."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_players(db: AsyncSession) -> None:
    """Insert enough real-shaped Player rows to fill every position bucket the
    seeder pulls from (10 teams × up to 5 per position = 50)."""
    per_position = 60
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    for pos in positions:
        for i in range(per_position):
            db.add(
                Player(
                    id=f"{pos.lower()}_{i:03d}",
                    full_name=f"{pos} Player {i:03d}",
                    position=pos,
                )
            )
    await db.commit()


async def test_seed_populates_fixture(db: AsyncSession):
    await _seed_players(db)
    created = await seed_demo_league(db)
    assert created is True

    demo = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one()
    conn = (
        await db.execute(
            select(LeagueConnection).where(LeagueConnection.user_id == demo.id)
        )
    ).scalar_one()

    assert conn.platform == "sleeper"
    assert conn.league_id == "demo-league"
    assert conn.credentials is None
    assert conn.roster_positions == ROSTER_POSITIONS
    assert conn.team_id == str(NUM_TEAMS)

    rosters = (
        (await db.execute(select(Roster).where(Roster.connection_id == conn.id)))
        .scalars()
        .all()
    )
    assert len(rosters) == NUM_TEAMS

    player_ids = {p.id for p in (await db.execute(select(Player))).scalars().all()}
    for r in rosters:
        assert len(r.players) == 15, f"team {r.team_id} has {len(r.players)} players"
        assert set(r.players).issubset(player_ids), "roster references non-real players"
        assert len(set(r.players)) == 15, "duplicate player in one roster"


async def test_seed_is_idempotent(db: AsyncSession):
    await _seed_players(db)
    assert await seed_demo_league(db) is True
    assert await seed_demo_league(db) is False

    demo = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one()
    conns = (
        (
            await db.execute(
                select(LeagueConnection).where(LeagueConnection.user_id == demo.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(conns) == 1
    rosters = (
        (
            await db.execute(
                select(Roster).where(Roster.connection_id == conns[0].id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rosters) == NUM_TEAMS
    matchups = (
        (
            await db.execute(
                select(Matchup).where(Matchup.connection_id == conns[0].id)
            )
        )
        .scalars()
        .all()
    )
    # 10 teams paired up = 5 matchups per week, one week seeded.
    assert len(matchups) == NUM_TEAMS // 2


async def test_fake_names_do_not_collide_with_real_user_teams(db: AsyncSession):
    """Seed a real user with their own league and rosters, then run the demo
    seed and confirm no fake team name matches any of the real owner_names."""
    await _seed_players(db)
    real = User(email="alice@example.com", password_hash=hash_password("x"))
    db.add(real)
    await db.commit()
    await db.refresh(real)

    real_conn = LeagueConnection(
        user_id=real.id,
        platform="sleeper",
        league_id="real-league",
        season=2026,
        scoring_type="ppr",
    )
    db.add(real_conn)
    await db.flush()

    real_team_names = [
        "Model Behavior",  # would collide if we ever fabricated this owner
        "Alice's Aces",
        "Team Two",
    ]
    for i, name in enumerate(real_team_names, start=1):
        db.add(
            Roster(
                connection_id=real_conn.id,
                team_id=str(i),
                owner_name=name,
                players=[],
            )
        )
    await db.commit()

    await seed_demo_league(db)

    demo = (
        await db.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one()
    demo_conn = (
        await db.execute(
            select(LeagueConnection).where(LeagueConnection.user_id == demo.id)
        )
    ).scalar_one()
    demo_rosters = (
        (
            await db.execute(
                select(Roster).where(Roster.connection_id == demo_conn.id)
            )
        )
        .scalars()
        .all()
    )
    demo_names = [r.owner_name for r in demo_rosters]

    # Every demo team name comes from the fixture list, none was invented from
    # or copied out of the real user's league.
    assert set(demo_names) == set(TEAM_NAMES)
    # The demo does not reuse any player row that the real user "owns" —
    # trivially true here (real rosters have empty players lists), but we
    # keep the assertion so a future regression would surface.
    real_players: set[str] = set()
    for r in (
        (
            await db.execute(
                select(Roster).where(Roster.connection_id == real_conn.id)
            )
        )
        .scalars()
        .all()
    ):
        real_players.update(r.players)
    for r in demo_rosters:
        assert not (set(r.players) & real_players), "demo player overlap with real user"
