import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import (
    AvailablePlayer,
    LeagueConnection,
    Matchup,
    MatchupOdds,
    Player,
    Roster,
    User,
)
from app.schemas.league import (
    ConnectLeagueRequest,
    EspnCredentialsRequest,
    EspnCredentialsResponse,
    EspnLeagueOption,
    EspnLookupRequest,
    EspnLookupResponse,
    EspnRefreshedLeague,
    LeagueConnectionResponse,
    MatchupResponse,
    RosterResponse,
    SleeperLeagueOption,
    SleeperLookupRequest,
    SleeperLookupResponse,
    StandingsEntry,
    WaiverPlayer,
)
from app.services.espn_service import discover_espn_leagues, normalize_swid
from app.services.schedule_service import current_nfl_week
from app.services.sleeper_service import SleeperClient
from app.services.sync_service import LeagueNotFoundError, sync_league, sync_live_scores
from app.utils.credentials import open_credentials, seal_credentials
from app.utils.fantasy_math import scoring_type_from_settings
from app.utils.security import block_demo, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


def _sync_failure(conn: LeagueConnection, exc: Exception) -> HTTPException:
    """A user-facing error for a failed league sync. The exception itself is
    logged, not returned — it can carry SQL, upstream URLs and internals."""
    logger.warning(
        "League sync failed for %s league %s", conn.platform, conn.league_id, exc_info=exc
    )
    platform = "ESPN" if conn.platform == "espn" else "Sleeper"
    code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    if isinstance(exc, LeagueNotFoundError):
        code = 404
    if code in (401, 403):
        detail = (
            f"{platform} refused access to that league — for a private league, "
            "your ESPN sign-in (the espn_s2 and SWID cookies) is missing or expired."
        )
    elif code == 404:
        detail = f"{platform} couldn't find that league — check the league ID and season."
    else:
        detail = f"Couldn't sync the league from {platform} — try again in a moment."
    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail)


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


@router.post("/espn/lookup", response_model=EspnLookupResponse)
async def espn_lookup(
    body: EspnLookupRequest,
    user: User = Depends(block_demo),
    db: AsyncSession = Depends(get_db),
):
    """The ESPN fantasy football leagues this ESPN account plays in, so the
    user picks one from a list (as with Sleeper) instead of copying a league ID
    out of a URL. The cookies are used for this one call and not stored."""
    try:
        leagues = await discover_espn_leagues(
            body.swid, body.espn_s2, get_settings().current_season
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ESPN league lookup failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Couldn't load your leagues from ESPN — enter the league's web address instead.",
        ) from exc

    connected = {
        (league_id, season)
        for league_id, season in (
            await db.execute(
                select(LeagueConnection.league_id, LeagueConnection.season).where(
                    LeagueConnection.user_id == user.id, LeagueConnection.platform == "espn"
                )
            )
        ).all()
    }
    return EspnLookupResponse(
        leagues=[
            EspnLeagueOption(**lg, connected=(lg["league_id"], lg["season"]) in connected)
            for lg in leagues
        ]
    )


def _uses_espn_account(conn: LeagueConnection, swid: str) -> bool:
    """True when a connected ESPN league signs in as this ESPN account — or
    has stored cookies we can no longer read, which only fresh ones can fix.
    Public leagues (no stored cookies) and leagues connected through a
    different ESPN account are left alone."""
    if not conn.credentials:
        return False
    stored = normalize_swid(open_credentials(conn.credentials).get("swid"))
    return stored is None or stored.upper() == swid.upper()


async def _espn_account_connections(
    db: AsyncSession, user: User, swid: str
) -> list[LeagueConnection]:
    """The user's private ESPN leagues that sign in as this ESPN account."""
    conns = (
        await db.execute(
            select(LeagueConnection)
            .where(LeagueConnection.user_id == user.id, LeagueConnection.platform == "espn")
            .order_by(LeagueConnection.created_at, LeagueConnection.id)
        )
    ).scalars().all()
    return [c for c in conns if _uses_espn_account(c, swid)]


async def _share_espn_cookies(
    db: AsyncSession, user: User, espn_s2: str, swid: str, skip: uuid.UUID
) -> bool:
    """Put cookies that just worked for one league on the user's other leagues
    under the same ESPN account. ESPN signs the whole account in or out at
    once, so when one league's cookies expire they all have — re-entering them
    for one league shouldn't leave the rest failing until each is redone.
    True if any league changed; the caller commits."""
    changed = False
    for conn in await _espn_account_connections(db, user, swid):
        if conn.id != skip:
            conn.credentials = seal_credentials({"espn_s2": espn_s2, "swid": swid})
            changed = True
    return changed


@router.post("/espn/credentials", response_model=EspnCredentialsResponse)
async def refresh_espn_credentials(
    body: EspnCredentialsRequest,
    user: User = Depends(block_demo),
    db: AsyncSession = Depends(get_db),
):
    """Replace the stored ESPN cookies on all of this user's private ESPN
    leagues and re-sync each one — the one-step fix for an expired ESPN
    sign-in. A league whose sync still fails keeps its old cookies."""
    conn_ids = [c.id for c in await _espn_account_connections(db, user, body.swid)]
    sealed = seal_credentials({"espn_s2": body.espn_s2, "swid": body.swid})
    results: list[EspnRefreshedLeague] = []
    # Each league is saved by its own sync (which commits), and rolled back on
    # its own if ESPN still refuses it.
    for conn_id in conn_ids:
        conn = await db.get(LeagueConnection, conn_id)
        if conn is None:
            continue
        name = conn.league_name
        conn.credentials = sealed
        try:
            await sync_league(db, conn)
        except Exception as exc:
            detail = _sync_failure(conn, exc).detail  # before rollback expires conn
            await db.rollback()
            results.append(
                EspnRefreshedLeague(id=str(conn_id), league_name=name, ok=False, detail=detail)
            )
            continue
        results.append(
            EspnRefreshedLeague(id=str(conn_id), league_name=conn.league_name, ok=True)
        )
    return EspnCredentialsResponse(leagues=results)


@router.post("/connect", response_model=LeagueConnectionResponse, status_code=201)
async def connect_league(
    body: ConnectLeagueRequest,
    user: User = Depends(block_demo),
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
    if existing and body.platform == "espn" and body.espn_s2 and body.swid:
        # Reconnecting a private ESPN league with fresh cookies: the old ones
        # expired (or can no longer be decrypted), so every sync was failing.
        # Swap them in and re-sync rather than forcing a disconnect, which
        # would throw away the league's history.
        existing.credentials = seal_credentials({"espn_s2": body.espn_s2, "swid": body.swid})
        try:
            await sync_league(db, existing)
        except Exception as exc:
            failure = _sync_failure(existing, exc)  # before rollback expires conn
            await db.rollback()
            raise failure from exc
        # These cookies just worked, and they belong to the whole ESPN account:
        # hand them to the user's other leagues on it, which expired together.
        if await _share_espn_cookies(db, user, body.espn_s2, body.swid, skip=existing.id):
            await db.commit()
        return _conn_response(existing)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "League already connected")

    credentials = None
    if body.platform == "espn" and body.espn_s2 and body.swid:
        credentials = seal_credentials({"espn_s2": body.espn_s2, "swid": body.swid})

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
        failure = _sync_failure(conn, exc)  # before rollback expires conn
        await db.rollback()
        raise failure from exc

    if conn.platform == "sleeper":
        conn.scoring_type = scoring_type_from_settings(conn.scoring_settings)
        await db.commit()
    elif body.espn_s2 and body.swid:
        if await _share_espn_cookies(db, user, body.espn_s2, body.swid, skip=conn.id):
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
    user: User = Depends(block_demo),
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
    user: User = Depends(block_demo),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_user_connection(db, user, connection_id)
    try:
        await sync_league(db, conn)
    except Exception as exc:
        failure = _sync_failure(conn, exc)  # before rollback expires conn
        await db.rollback()
        raise failure from exc
    return _conn_response(conn)


@router.delete("/{connection_id}", status_code=204)
async def disconnect_league(
    connection_id: str,
    user: User = Depends(block_demo),
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
    def win_pct(e: StandingsEntry) -> float:
        games = e.wins + e.losses + e.ties
        return (e.wins + 0.5 * e.ties) / games if games else 0.0

    # Ties count as half a win (5-0-1 ranks above 5-1-0); points for breaks ties.
    return sorted(entries, key=lambda e: (-win_pct(e), -e.wins, -e.points_for))


@router.get("/{connection_id}/matchup", response_model=MatchupResponse)
async def get_matchup(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.gameplan_service import resolve_current_matchup

    conn = await _get_user_connection(db, user, connection_id)
    # The current NFL week's matchup — the same one the Matchup page and game
    # plan show. (Picking "the earliest week nobody has scored in yet" jumped to
    # next week's opponent as soon as Sunday's games put points on the board.)
    m = await resolve_current_matchup(db, conn)
    if m is None:
        any_week = (
            await db.execute(
                select(Matchup.week)
                .where(Matchup.connection_id == conn.id)
                .order_by(Matchup.week.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if any_week is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No matchup data — sync the league")
    latest_week = m.week if m else any_week

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


@router.get("/{connection_id}/matchup/preview")
async def get_matchup_preview(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Head-to-head scouting report: projected totals, win probability, and
    position-by-position battles. Powered by the projection engine."""
    from app.services.gameplan_service import build_matchup_preview

    conn = await _get_user_connection(db, user, connection_id)
    return await build_matchup_preview(db, conn)


@router.post("/{connection_id}/matchup/refresh")
async def refresh_live_scores(
    connection_id: str,
    user: User = Depends(block_demo),
    db: AsyncSession = Depends(get_db),
):
    """Pull just the current matchup's live points (cheap — safe to poll), then
    return the recomputed preview with updated odds."""
    from app.services.gameplan_service import build_matchup_preview

    conn = await _get_user_connection(db, user, connection_id)
    try:
        await sync_live_scores(db, conn)
    except Exception as exc:
        # Unhandled, this was a bare 500 with no CORS headers, which the page
        # could only report as "couldn't reach the server" every poll — hiding
        # the usual cause, an expired ESPN sign-in.
        failure = _sync_failure(conn, exc)  # before rollback expires conn
        await db.rollback()
        raise failure from exc
    return await build_matchup_preview(db, conn)


@router.get("/{connection_id}/matchup/odds-history")
async def get_odds_history(
    connection_id: str,
    week: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Win-probability timeline for a matchup week (defaults to the week with the
    most recent snapshot — the one being played): every snapshot since the
    first kickoff, the week's kickoffs, and the big swings with the players
    whose points caused them."""
    from app.services.odds_timeline import build_odds_history, week_kickoffs

    conn = await _get_user_connection(db, user, connection_id)
    if week is None:
        week = (
            await db.execute(
                select(MatchupOdds.week)
                .where(MatchupOdds.connection_id == conn.id)
                .order_by(MatchupOdds.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if week is None:
        return {"week": None, "points": [], "kickoffs": [], "window_start": None}
    rows = (
        await db.execute(
            select(MatchupOdds)
            .where(MatchupOdds.connection_id == conn.id, MatchupOdds.week == week)
            .order_by(MatchupOdds.captured_at.asc(), MatchupOdds.id.asc())
        )
    ).scalars().all()
    kickoffs = await week_kickoffs(db, conn.season, week)
    return {"week": week, **build_odds_history(list(rows), kickoffs)}


# Fantasy playoffs are the NFL's weeks 15-17 in most leagues.
FANTASY_PLAYOFF_START = 15
FANTASY_PLAYOFF_WEEKS = 3


@router.get("/{connection_id}/schedule-strength")
async def schedule_strength(
    connection_id: str,
    window: str = "upcoming",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Heatmap of matchup difficulty for the user's roster.

    window="upcoming" (default) shows the next several weeks from the current
    week; window="playoffs" shows the fantasy playoff weeks (NFL 15-17) so you
    can scout postseason matchups ahead of time.
    """
    from app.services.schedule_service import build_schedule_strength

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

    if window == "playoffs":
        return await build_schedule_strength(
            db,
            conn.season,
            FANTASY_PLAYOFF_START,
            list(roster.players),
            weeks_ahead=FANTASY_PLAYOFF_WEEKS,
        )

    # The schedule's week is the app's one definition of "this week"; Sleeper's
    # clock is only a fallback for when no schedule is loaded.
    week = await current_nfl_week(db, conn.season)
    if week is None:
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
            recent_ppr_avg=(
                float(ap.recent_ppr_avg) if ap.recent_ppr_avg is not None else None
            ),
        )
        for ap, p in rows
    ]
