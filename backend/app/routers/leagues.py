import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import (
    AvailablePlayer,
    LeagueConnection,
    Matchup,
    Player,
    Roster,
    User,
)
from app.schemas.league import (
    ConnectLeagueRequest,
    LeagueConnectionResponse,
    MatchupResponse,
    RosterResponse,
    SleeperLeagueOption,
    SleeperLookupRequest,
    SleeperLookupResponse,
    StandingsEntry,
    WaiverPlayer,
)
from app.services.sleeper_service import SleeperClient
from app.services.sync_service import sync_league
from app.utils.fantasy_math import scoring_type_from_settings
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


def _conn_response(conn: LeagueConnection) -> LeagueConnectionResponse:
    return LeagueConnectionResponse(
        id=str(conn.id),
        platform=conn.platform,
        league_id=conn.league_id,
        league_name=conn.league_name,
        season=conn.season,
        scoring_type=conn.scoring_type,
        roster_positions=conn.roster_positions,
        team_id=conn.team_id,
        last_synced_at=conn.last_synced_at,
    )


async def _get_user_connection(
    db: AsyncSession, user: User, connection_id: str
) -> LeagueConnection:
    try:
        cid = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid connection id")
    conn = (
        await db.execute(
            select(LeagueConnection).where(
                LeagueConnection.id == cid, LeagueConnection.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "League connection not found")
    return conn


@router.post("/sleeper/lookup", response_model=SleeperLookupResponse)
async def sleeper_lookup(body: SleeperLookupRequest, _: User = Depends(get_current_user)):
    client = SleeperClient()
    try:
        sleeper_user = await client.get_user(body.username.strip())
        if sleeper_user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Sleeper user not found")
        season = get_settings().current_season
        leagues = await client.get_user_leagues(sleeper_user["user_id"], season)
        if not leagues:
            # Fall back to the previous season (useful in the offseason)
            leagues = await client.get_user_leagues(sleeper_user["user_id"], season - 1)
    finally:
        await client.close()

    return SleeperLookupResponse(
        user_id=sleeper_user["user_id"],
        username=sleeper_user.get("display_name") or body.username,
        leagues=[
            SleeperLeagueOption(
                league_id=lg["league_id"],
                name=lg.get("name", "Unnamed league"),
                season=str(lg.get("season", season)),
                total_rosters=lg.get("total_rosters", 0),
                scoring_type=scoring_type_from_settings(lg.get("scoring_settings")),
            )
            for lg in leagues
        ],
    )


@router.post("/connect", response_model=LeagueConnectionResponse, status_code=201)
async def connect_league(
    body: ConnectLeagueRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.platform not in ("sleeper", "espn"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported platform")

    existing = (
        await db.execute(
            select(LeagueConnection).where(
                LeagueConnection.user_id == user.id,
                LeagueConnection.platform == body.platform,
                LeagueConnection.league_id == body.league_id,
                LeagueConnection.season == body.season,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "League already connected")

    credentials = None
    if body.platform == "espn" and body.espn_s2 and body.swid:
        credentials = {"espn_s2": body.espn_s2, "swid": body.swid}

    conn = LeagueConnection(
        user_id=user.id,
        platform=body.platform,
        platform_user_id=body.platform_user_id,
        league_id=body.league_id,
        season=body.season,
        credentials=credentials,
        team_id=body.team_id,
    )
    db.add(conn)
    await db.flush()

    try:
        await sync_league(db, conn)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Failed to sync league: {exc}"
        ) from exc

    if conn.platform == "sleeper":
        conn.scoring_type = scoring_type_from_settings(conn.scoring_settings)
        await db.commit()
    return _conn_response(conn)


@router.get("", response_model=list[LeagueConnectionResponse])
async def list_leagues(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    conns = (
        (
            await db.execute(
                select(LeagueConnection).where(LeagueConnection.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    return [_conn_response(c) for c in conns]


@router.post("/{connection_id}/claim-team", response_model=LeagueConnectionResponse)
async def claim_team(
    connection_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set which team in the league belongs to this user (for platforms
    where it can't be inferred automatically, e.g. public ESPN leagues)."""
    conn = await _get_user_connection(db, user, connection_id)
    team_id = str(body.get("team_id", "")).strip()
    if not team_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id is required")
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == team_id
            )
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such team in this league")
    conn.team_id = team_id
    await db.commit()
    return _conn_response(conn)


@router.post("/{connection_id}/sync", response_model=LeagueConnectionResponse)
async def trigger_sync(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    await sync_league(db, conn)
    return _conn_response(conn)


@router.delete("/{connection_id}", status_code=204)
async def disconnect_league(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    await db.delete(conn)
    await db.commit()


async def _roster_to_response(db: AsyncSession, roster: Roster) -> RosterResponse:
    all_ids = list(roster.players or [])
    players = (
        (await db.execute(select(Player).where(Player.id.in_(all_ids)))).scalars().all()
        if all_ids
        else []
    )
    by_id = {p.id: p for p in players}
    starter_ids = roster.starters or []

    def card(pid: str) -> dict:
        p = by_id.get(pid)
        if p is None:
            return {"id": pid, "name": "Unknown", "position": None, "team": None}
        return {
            "id": p.id,
            "name": p.full_name,
            "position": p.position,
            "team": p.team,
            "injury_status": p.injury_status,
            "status": p.status,
        }

    return RosterResponse(
        team_id=roster.team_id,
        owner_name=roster.owner_name,
        wins=roster.wins,
        losses=roster.losses,
        ties=roster.ties,
        points_for=float(roster.points_for or 0),
        points_against=float(roster.points_against or 0),
        starters=[card(pid) for pid in starter_ids],
        bench=[card(pid) for pid in all_ids if pid not in set(starter_ids)],
    )


@router.get("/{connection_id}/roster", response_model=RosterResponse)
async def get_roster(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    if not conn.team_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Your team is not identified yet — sync the league")
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == conn.team_id
            )
        )
    ).scalar_one_or_none()
    if roster is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Roster not found — sync the league")
    return await _roster_to_response(db, roster)


@router.get("/{connection_id}/standings", response_model=list[StandingsEntry])
async def get_standings(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    rosters = (
        (await db.execute(select(Roster).where(Roster.connection_id == conn.id)))
        .scalars()
        .all()
    )
    entries = [
        StandingsEntry(
            team_id=r.team_id,
            owner_name=r.owner_name,
            wins=r.wins,
            losses=r.losses,
            ties=r.ties,
            points_for=float(r.points_for or 0),
            points_against=float(r.points_against or 0),
        )
        for r in rosters
    ]
    return sorted(entries, key=lambda e: (-e.wins, -e.points_for))


@router.get("/{connection_id}/matchup", response_model=MatchupResponse)
async def get_matchup(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    latest_week = (
        await db.execute(
            select(Matchup.week)
            .where(Matchup.connection_id == conn.id)
            .order_by(Matchup.week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_week is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matchup data — sync the league")

    m = (
        await db.execute(
            select(Matchup).where(
                Matchup.connection_id == conn.id,
                Matchup.week == latest_week,
                or_(
                    Matchup.team_a_id == conn.team_id,
                    Matchup.team_b_id == conn.team_id,
                ),
            )
        )
    ).scalar_one_or_none()

    async def roster_resp(team_id: str | None) -> RosterResponse | None:
        if team_id is None:
            return None
        r = (
            await db.execute(
                select(Roster).where(
                    Roster.connection_id == conn.id, Roster.team_id == team_id
                )
            )
        ).scalar_one_or_none()
        return await _roster_to_response(db, r) if r else None

    if m is None:
        return MatchupResponse(week=latest_week, user_team=await roster_resp(conn.team_id), opponent_team=None)

    opp_id = m.team_b_id if m.team_a_id == conn.team_id else m.team_a_id
    return MatchupResponse(
        week=latest_week,
        user_team=await roster_resp(conn.team_id),
        opponent_team=await roster_resp(opp_id),
    )


@router.get("/{connection_id}/schedule-strength")
async def schedule_strength(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Heatmap of upcoming matchup difficulty for the user's roster."""
    from app.services.schedule_service import build_schedule_strength
    from app.services.sleeper_service import SleeperClient

    conn = await _get_user_connection(db, user, connection_id)
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == conn.team_id
            )
        )
    ).scalar_one_or_none()
    if roster is None or not roster.players:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No roster — sync the league first")

    week = 1
    try:
        client = SleeperClient()
        try:
            state = await client.get_nfl_state()
            week = int(state.get("week") or 1)
        finally:
            await client.close()
    except Exception:
        pass

    return await build_schedule_strength(
        db, conn.season, max(week, 1), list(roster.players)
    )


@router.get("/{connection_id}/waivers", response_model=list[WaiverPlayer])
async def get_waivers(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    rows = (
        await db.execute(
            select(AvailablePlayer, Player)
            .join(Player, Player.id == AvailablePlayer.player_id)
            .where(AvailablePlayer.connection_id == conn.id)
            .order_by(AvailablePlayer.trending_count.desc().nulls_last())
            .limit(50)
        )
    ).all()
    return [
        WaiverPlayer(
            player={
                "id": p.id,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "injury_status": p.injury_status,
            },
            trending_count=ap.trending_count,
            recent_ppr_avg=float(ap.recent_ppr_avg) if ap.recent_ppr_avg else None,
        )
        for ap, p in rows
    ]
