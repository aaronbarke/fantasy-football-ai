"""League data synchronization — pulls platform state into our DB."""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AvailablePlayer,
    LeagueConnection,
    Matchup,
    Player,
    PlayerStatsWeekly,
    Roster,
)
from app.services.espn_service import ESPNClient
from app.services.sleeper_service import SleeperClient
from app.utils.constants import FANTASY_POSITIONS
from app.utils.player_id_map import espn_to_sleeper_map

logger = logging.getLogger(__name__)


async def sync_player_pool(db: AsyncSession) -> int:
    """Refresh the players master table from Sleeper's full player dump.
    Run at most once per day."""
    client = SleeperClient()
    try:
        all_players = await client.get_all_players()
    finally:
        await client.close()

    count = 0
    for pid, p in all_players.items():
        position = p.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        player = await db.get(Player, pid)
        if player is None:
            player = Player(id=pid, full_name=p.get("full_name") or pid)
            db.add(player)
        player.full_name = p.get("full_name") or player.full_name or pid
        player.first_name = p.get("first_name")
        player.last_name = p.get("last_name")
        player.position = position
        player.team = p.get("team")
        player.age = p.get("age")
        player.years_exp = p.get("years_exp")
        player.status = p.get("status")
        player.injury_status = p.get("injury_status") or player.injury_status
        player.injury_body_part = p.get("injury_body_part") or player.injury_body_part
        player.depth_chart_order = p.get("depth_chart_order")
        if p.get("espn_id"):
            player.espn_id = str(p["espn_id"])
        if p.get("yahoo_id"):
            player.yahoo_id = str(p["yahoo_id"])
        if p.get("gsis_id"):
            player.gsis_id = str(p["gsis_id"]).strip()
        count += 1
        if count % 1000 == 0:
            await db.flush()
    await db.commit()
    logger.info("Player pool sync: %d fantasy-relevant players", count)
    return count


async def sync_sleeper_league(db: AsyncSession, conn: LeagueConnection) -> None:
    client = SleeperClient()
    try:
        league = await client.get_league(conn.league_id)
        rosters = await client.get_rosters(conn.league_id)
        users = await client.get_league_users(conn.league_id)
        state = await client.get_nfl_state()
        week = int(state.get("week") or 1)
        matchups = await client.get_matchups(conn.league_id, week)
        trending = await client.get_trending("add", limit=200)
    finally:
        await client.close()

    if league:
        conn.league_name = league.get("name")
        conn.scoring_settings = league.get("scoring_settings")
        conn.roster_positions = league.get("roster_positions")

    owner_names = {
        u["user_id"]: (u.get("metadata") or {}).get("team_name") or u.get("display_name")
        for u in users
    }

    # Rosters
    rostered_ids: set[str] = set()
    for r in rosters:
        team_id = str(r["roster_id"])
        players = [str(p) for p in (r.get("players") or [])]
        rostered_ids.update(players)
        settings = r.get("settings") or {}

        roster = (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == team_id
                )
            )
        ).scalar_one_or_none()
        if roster is None:
            roster = Roster(connection_id=conn.id, team_id=team_id, players=[])
            db.add(roster)

        roster.owner_name = owner_names.get(r.get("owner_id"))
        roster.players = players
        roster.starters = [str(p) for p in (r.get("starters") or [])]
        roster.wins = settings.get("wins", 0)
        roster.losses = settings.get("losses", 0)
        roster.ties = settings.get("ties", 0)
        roster.points_for = settings.get("fpts", 0) or 0
        roster.points_against = settings.get("fpts_against", 0) or 0

        # Identify which roster belongs to the connected user
        if conn.platform_user_id and r.get("owner_id") == conn.platform_user_id:
            conn.team_id = team_id

    # Matchups: Sleeper returns one row per roster with a shared matchup_id
    by_matchup: dict[int, list[dict]] = {}
    for m in matchups:
        if m.get("matchup_id") is not None:
            by_matchup.setdefault(m["matchup_id"], []).append(m)

    await db.execute(
        delete(Matchup).where(Matchup.connection_id == conn.id, Matchup.week == week)
    )
    for pair in by_matchup.values():
        a = pair[0]
        b = pair[1] if len(pair) > 1 else {}
        db.add(
            Matchup(
                connection_id=conn.id,
                week=week,
                team_a_id=str(a.get("roster_id")),
                team_b_id=str(b.get("roster_id")) if b else None,
                team_a_points=a.get("points"),
                team_b_points=b.get("points") if b else None,
            )
        )

    # Waiver wire: trending players not rostered in this league
    await db.execute(delete(AvailablePlayer).where(AvailablePlayer.connection_id == conn.id))
    season = conn.season
    for t in trending:
        pid = str(t.get("player_id"))
        if pid in rostered_ids:
            continue
        player = await db.get(Player, pid)
        if player is None or player.position not in FANTASY_POSITIONS:
            continue
        recent = (
            await db.execute(
                select(PlayerStatsWeekly.fantasy_points_ppr)
                .where(
                    PlayerStatsWeekly.player_id == pid,
                    PlayerStatsWeekly.season == season,
                )
                .order_by(PlayerStatsWeekly.week.desc())
                .limit(3)
            )
        ).scalars().all()
        recent_vals = [float(x) for x in recent if x is not None]
        avg = round(sum(recent_vals) / len(recent_vals), 1) if recent_vals else None
        db.add(
            AvailablePlayer(
                connection_id=conn.id,
                player_id=pid,
                trending_count=t.get("count"),
                recent_ppr_avg=avg,
            )
        )

    conn.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    logger.info("Synced sleeper league %s (week %d)", conn.league_id, week)


async def sync_espn_league(db: AsyncSession, conn: LeagueConnection) -> None:
    creds = conn.credentials or {}
    client = ESPNClient(
        league_id=conn.league_id,
        season=conn.season,
        espn_s2=creds.get("espn_s2"),
        swid=creds.get("swid"),
    )
    try:
        data = await client.get_rosters()
    finally:
        await client.close()

    conn.league_name = (data.get("settings") or {}).get("name") or conn.league_name
    espn_map = await espn_to_sleeper_map(db)

    # Identify the user's team from their SWID cookie (ESPN owner GUIDs are SWIDs)
    swid = (creds.get("swid") or "").strip().upper()
    if not conn.team_id and swid:
        for team in data.get("teams", []):
            owners = [str(o).upper() for o in (team.get("owners") or [])]
            if swid in owners:
                conn.team_id = str(team["id"])
                break

    for team in data.get("teams", []):
        team_id = str(team["id"])
        espn_ids, espn_starter_ids = ESPNClient.parse_roster_entries(team)
        players = [espn_map[e] for e in espn_ids if e in espn_map]
        starters = [espn_map[e] for e in espn_starter_ids if e in espn_map]

        roster = (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == team_id
                )
            )
        ).scalar_one_or_none()
        if roster is None:
            roster = Roster(connection_id=conn.id, team_id=team_id, players=[])
            db.add(roster)

        record = ((team.get("record") or {}).get("overall")) or {}
        roster.owner_name = team.get("name") or f"Team {team_id}"
        roster.players = players
        roster.starters = starters
        roster.wins = record.get("wins", 0)
        roster.losses = record.get("losses", 0)
        roster.ties = record.get("ties", 0)
        roster.points_for = record.get("pointsFor", 0) or 0
        roster.points_against = record.get("pointsAgainst", 0) or 0

    conn.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    logger.info("Synced espn league %s", conn.league_id)


async def sync_league(db: AsyncSession, conn: LeagueConnection) -> None:
    if conn.platform == "sleeper":
        await sync_sleeper_league(db, conn)
    elif conn.platform == "espn":
        await sync_espn_league(db, conn)
    else:
        raise ValueError(f"Unsupported platform: {conn.platform}")
