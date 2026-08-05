import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import LeagueConnection, MockDraft, Roster, User
from app.services.adp_service import SCORING_FORMATS
from app.services.draft_service import recommend_picks
from app.services.mock_draft_service import (
    advance,
    build_pool,
    grade,
    load_picks,
    make_rng,
    make_user_pick,
    snake_slot,
    user_pick_numbers,
)
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/mock", tags=["mock draft"])


class CreateMockRequest(BaseModel):
    connection_id: str | None = None
    scoring: str | None = None
    teams: int = Field(default=12, ge=4, le=16)
    rounds: int = Field(default=15, ge=1, le=25)
    my_slot: int = Field(default=1, ge=1, le=16)


class MockPickRequest(BaseModel):
    player_id: str


async def _league_defaults(
    db: AsyncSession, conn: LeagueConnection
) -> tuple[int | None, int | None]:
    """(team count, draftable rounds) inferred from a connected league, or None."""
    teams = None
    synced = (
        await db.execute(
            select(func.count(Roster.id)).where(Roster.connection_id == conn.id)
        )
    ).scalar()
    if synced:
        teams = int(synced)
    rounds = None
    if conn.roster_positions:
        draftable = [
            s for s in conn.roster_positions if s.upper() not in ("IR", "TAXI")
        ]
        if draftable:
            rounds = len(draftable)
    return teams, rounds


async def _get_draft(db: AsyncSession, user: User, draft_id: str) -> MockDraft:
    try:
        did = uuid.UUID(draft_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid draft id")
    draft = (
        await db.execute(
            select(MockDraft).where(
                MockDraft.id == did, MockDraft.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mock draft not found")
    return draft


async def _state(db: AsyncSession, draft: MockDraft, picks: list[dict]) -> dict:
    """The client's whole view of the draft: who's gone, whose turn, your roster."""
    total = draft.teams * draft.rounds
    made = len(picks)
    on_the_clock = made + 1 if made < total else None
    rnd, slot = snake_slot(on_the_clock, draft.teams) if on_the_clock else (None, None)
    my_picks = user_pick_numbers(draft.teams, draft.my_slot, draft.rounds)
    upcoming = [p for p in my_picks if p > made]

    return {
        "id": str(draft.id),
        "season": draft.season,
        "scoring": draft.scoring,
        "teams": draft.teams,
        "rounds": draft.rounds,
        "my_slot": draft.my_slot,
        "status": draft.status,
        "picks_made": made,
        "total_picks": total,
        "on_the_clock": on_the_clock,
        "current_round": rnd,
        "current_slot": slot,
        "is_my_turn": slot == draft.my_slot if slot else False,
        "next_pick": upcoming[0] if upcoming else None,
        "following_pick": upcoming[1] if len(upcoming) > 1 else None,
        "picks": picks,
        "my_player_ids": [p["player_id"] for p in picks if p["is_user"]],
        "drafted_ids": [p["player_id"] for p in picks],
    }


@router.post("", status_code=201)
async def create_mock(
    body: CreateMockRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a mock draft and run the bots up to your first pick."""
    scoring = body.scoring
    roster_positions = None
    teams = body.teams
    rounds = body.rounds
    if body.connection_id:
        try:
            cid = uuid.UUID(body.connection_id)
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
        scoring = scoring or conn.scoring_type
        roster_positions = conn.roster_positions
        # Auto-configure from the real league when the request kept the form
        # defaults, so a connected user gets their actual size and depth without
        # having to know them. An explicit non-default choice still wins.
        league_teams, league_rounds = await _league_defaults(db, conn)
        if teams == CreateMockRequest.model_fields["teams"].default and league_teams:
            teams = league_teams
        if rounds == CreateMockRequest.model_fields["rounds"].default and league_rounds:
            rounds = league_rounds

    if body.my_slot > teams:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Your slot is outside the league size"
        )
    scoring = scoring if scoring in SCORING_FORMATS else "ppr"
    season = get_settings().current_season

    pool = await build_pool(db, season, scoring, teams, roster_positions)
    if not pool:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No draft board yet — draft data hasn't been synced",
        )

    draft = MockDraft(
        user_id=user.id,
        season=season,
        scoring=scoring,
        teams=teams,
        rounds=rounds,
        my_slot=body.my_slot,
        roster_positions=roster_positions,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    picks = await advance(db, draft, pool, make_rng(draft.id, 0))
    return await _state(db, draft, picks)


@router.get("/config")
async def mock_config(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Suggested mock settings for a connected league, to pre-fill the setup form."""
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
    teams, rounds = await _league_defaults(db, conn)
    return {
        "teams": teams,
        "rounds": rounds,
        "scoring": conn.scoring_type,
        "league_name": conn.league_name,
    }


@router.get("")
async def list_mocks(
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    drafts = (
        (
            await db.execute(
                select(MockDraft)
                .where(MockDraft.user_id == user.id)
                .order_by(MockDraft.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(d.id),
            "teams": d.teams,
            "rounds": d.rounds,
            "my_slot": d.my_slot,
            "scoring": d.scoring,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in drafts
    ]


@router.get("/{draft_id}")
async def get_mock(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draft = await _get_draft(db, user, draft_id)
    picks = await load_picks(db, draft.id)
    state = await _state(db, draft, picks)

    pool = await build_pool(
        db, draft.season, draft.scoring, draft.teams, draft.roster_positions
    )
    taken = set(state["drafted_ids"])
    state["available"] = [p for p in pool if p["player_id"] not in taken][:200]
    # Split the pool: VOR players are the value board, K/DEF ride the urgency
    # ramp inside recommend_picks so they surface only when the draft is ending.
    state["recommendations"] = recommend_picks(
        [p for p in pool if p.get("overall_rank")],
        draft.roster_positions,
        state["my_player_ids"],
        state["drafted_ids"],
        state["next_pick"],
        state["following_pick"],
        limit=4,
        late_round=[p for p in pool if not p.get("overall_rank")],
        rounds=draft.rounds,
    )
    return state


@router.post("/{draft_id}/pick")
async def submit_pick(
    draft_id: str,
    body: MockPickRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draft = await _get_draft(db, user, draft_id)
    if draft.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This mock draft is finished")

    pool = await build_pool(
        db, draft.season, draft.scoring, draft.teams, draft.roster_positions
    )
    existing = await load_picks(db, draft.id)
    try:
        picks = await make_user_pick(
            db, draft, pool, body.player_id, make_rng(draft.id, len(existing))
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return await _state(db, draft, picks)


@router.get("/{draft_id}/results")
async def mock_results(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draft = await _get_draft(db, user, draft_id)
    picks = await load_picks(db, draft.id)
    if not picks:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing drafted yet")
    return grade(picks, draft.teams, draft.my_slot)


@router.delete("/{draft_id}", status_code=204)
async def delete_mock(
    draft_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    draft = await _get_draft(db, user, draft_id)
    await db.delete(draft)
    await db.commit()
