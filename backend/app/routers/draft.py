import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import LeagueConnection, Roster, User
from app.services.adp_service import SCORING_FORMATS
from app.services.ai_service import generate_response
from app.services.draft_service import (
    availability_at,
    compute_draft_board,
    late_round_board,
    recommend_picks,
    replacement_ranks,
    roster_needs,
)
from app.services.live_draft_service import espn_live_draft_state
from app.services.news_service import recent_news_by_player
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/draft", tags=["draft"])

DEFAULT_LEAGUE_SIZE = 12
NEWS_FOR_TOP_N = 60

ADVICE_QUESTION = (
    "You are on the clock in a live fantasy football draft. You are given the "
    "computed draft board (our own season-long projections expressed as VOR, "
    "positional tiers, consensus ADP, and the probability each player survives "
    "until the next pick), the roster already drafted, and the top ranked "
    "candidates with their reasoning. Make the call: name who to take and why "
    "in one or two sentences, then give two alternatives with a sentence each. "
    "Reference tier cliffs and whether a player can be waited on — if someone "
    "is very likely to still be there at the next pick, say so and take the "
    "player who won't be. Be decisive and brief; the clock is running."
)


DEFAULT_ROUNDS = 16


class RecommendRequest(BaseModel):
    connection_id: str | None = None
    scoring: str | None = None
    league_size: int | None = Field(default=None, ge=4, le=32)
    my_player_ids: list[str] = Field(default_factory=list)
    drafted_ids: list[str] = Field(default_factory=list)
    next_pick: int | None = Field(default=None, ge=1)
    following_pick: int | None = Field(default=None, ge=1)
    rounds: int | None = Field(default=None, ge=1, le=30)
    limit: int = Field(default=5, ge=1, le=25)


async def _get_conn(
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


async def _league_size(db: AsyncSession, conn: LeagueConnection) -> int:
    """Team count from the synced rosters — Sleeper doesn't give it to us directly."""
    count = (
        await db.execute(
            select(func.count(Roster.id)).where(Roster.connection_id == conn.id)
        )
    ).scalar()
    return int(count) if count else DEFAULT_LEAGUE_SIZE


@router.get("/board")
async def draft_board(
    connection_id: str | None = None,
    scoring: str | None = None,
    league_size: int | None = Query(default=None, ge=4, le=32),
    next_pick: int | None = Query(default=None, ge=1),
    limit: int = Query(default=300, ge=1, le=600),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ranked draft board. Defaults to the connected league's own settings."""
    season = get_settings().current_season
    roster_positions = None

    if connection_id:
        conn = await _get_conn(db, user, connection_id)
        scoring = scoring or conn.scoring_type
        roster_positions = conn.roster_positions
        if league_size is None:
            league_size = await _league_size(db, conn)

    scoring = scoring if scoring in SCORING_FORMATS else "ppr"
    league_size = league_size or DEFAULT_LEAGUE_SIZE

    board = await compute_draft_board(
        db,
        season=season,
        scoring=scoring,
        league_size=league_size,
        roster_positions=roster_positions,
    )

    # "Will he last?" only means something once we know which pick is yours.
    if next_pick:
        for row in board:
            row["available_at_next_pick"] = availability_at(
                row["adp"], row["adp_stdev"], next_pick
            )

    return {
        "season": season,
        "scoring": scoring,
        "league_size": league_size,
        "next_pick": next_pick,
        "replacement_ranks": replacement_ranks(roster_positions, league_size),
        "count": len(board),
        "players": board[:limit],
        # Kept apart from the ranked board on purpose — see VOR_POSITIONS.
        "late_round": await late_round_board(db, season, scoring),
        "news": await recent_news_by_player(
            db, [r["player_id"] for r in board[:NEWS_FOR_TOP_N]]
        ),
    }


async def _board_for(
    db: AsyncSession, user: User, body: RecommendRequest
) -> tuple[list[dict], str, int, list[str] | None]:
    """Shared setup: resolve league settings, then build the board."""
    season = get_settings().current_season
    scoring = body.scoring
    league_size = body.league_size
    roster_positions = None

    if body.connection_id:
        conn = await _get_conn(db, user, body.connection_id)
        scoring = scoring or conn.scoring_type
        roster_positions = conn.roster_positions
        if league_size is None:
            league_size = await _league_size(db, conn)

    scoring = scoring if scoring in SCORING_FORMATS else "ppr"
    league_size = league_size or DEFAULT_LEAGUE_SIZE
    board = await compute_draft_board(
        db,
        season=season,
        scoring=scoring,
        league_size=league_size,
        roster_positions=roster_positions,
    )
    return board, scoring, league_size, roster_positions


@router.get("/live")
async def live_draft(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live state of the connected league's real draft, for the draft room to
    poll and auto-mark picks. ESPN only — Sleeper support can follow the same
    shape. Returns a `not_started` shell for platforms without a live feed."""
    conn = await _get_conn(db, user, connection_id)
    if conn.platform != "espn":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Live draft sync is only available for ESPN leagues right now",
        )
    return await espn_live_draft_state(db, conn)


@router.post("/recommend")
async def draft_recommend(
    body: RecommendRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Best available for *your* pick, given your roster and where you sit."""
    board, scoring, league_size, roster_positions = await _board_for(db, user, body)
    if not board:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No draft board yet — draft data hasn't been synced",
        )

    season = get_settings().current_season
    rounds = body.rounds or (
        len(roster_positions) if roster_positions else DEFAULT_ROUNDS
    )
    picks = recommend_picks(
        board,
        roster_positions,
        body.my_player_ids,
        body.drafted_ids,
        body.next_pick,
        body.following_pick,
        body.limit,
        late_round=await late_round_board(db, season, scoring),
        rounds=rounds,
    )
    by_id = {r["player_id"]: r for r in board}
    my_positions = [
        by_id[pid]["position"] for pid in body.my_player_ids if pid in by_id
    ]
    return {
        "scoring": scoring,
        "league_size": league_size,
        "next_pick": body.next_pick,
        "following_pick": body.following_pick,
        "needs": roster_needs(roster_positions, my_positions),
        "recommendations": picks,
    }


@router.post("/advice")
async def draft_advice(
    body: RecommendRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The same recommendation, written up by Claude."""
    board, scoring, league_size, roster_positions = await _board_for(db, user, body)
    if not board:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No draft board yet — draft data hasn't been synced",
        )

    season = get_settings().current_season
    rounds = body.rounds or (
        len(roster_positions) if roster_positions else DEFAULT_ROUNDS
    )
    picks = recommend_picks(
        board,
        roster_positions,
        body.my_player_ids,
        body.drafted_ids,
        body.next_pick,
        body.following_pick,
        limit=6,
        late_round=await late_round_board(db, season, scoring),
        rounds=rounds,
    )
    by_id = {r["player_id"]: r for r in board}
    my_roster = [
        {
            "name": by_id[pid]["name"],
            "position": by_id[pid]["position"],
            "bye_week": by_id[pid].get("bye_week"),
        }
        for pid in body.my_player_ids
        if pid in by_id
    ]

    # Latest news on the players in play, so the AI weighs camp reports, injury
    # updates, and role changes the static projection can't see.
    news = await recent_news_by_player(
        db, [pick["player_id"] for pick in picks], per_player=2
    )

    context = {
        "question_type": "draft",
        "season": get_settings().current_season,
        "league_settings": {
            "scoring": scoring,
            "league_size": league_size,
            "roster_positions": roster_positions,
        },
        "your_pick": body.next_pick,
        "your_following_pick": body.following_pick,
        "your_roster": my_roster,
        "roster_needs": roster_needs(
            roster_positions, [p["position"] for p in my_roster]
        ),
        "candidates": [
            {
                **{
                    key: pick[key]
                    for key in (
                        "name",
                        "position",
                        "team",
                        "tier",
                        "proj_points",
                        "vor",
                        "adp",
                        "adp_delta",
                        "market_edge",
                        "is_tier_end",
                        "available_at_following_pick",
                        "injury_status",
                        "roster_status",
                        "bye_week",
                        "reasons",
                    )
                },
                "recent_news": [
                    n["headline"] for n in news.get(pick["player_id"], [])
                ],
            }
            for pick in picks
        ],
    }
    analysis = await generate_response(ADVICE_QUESTION, context)
    return {"analysis": analysis, "recommendations": picks}
