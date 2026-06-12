import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ChatMessage, LeagueConnection, Recommendation, User
from app.schemas.chat import ChatHistoryMessage, ChatRequest, ChatResponse
from app.services.ai_service import generate_response, stream_response
from app.services.context_builder import build_context
from app.services.sleeper_service import SleeperClient
from app.utils.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_TURNS = 8  # prior messages included for conversation continuity

PICK_RE = re.compile(r"\n?PICK:\s*(.+?)\s*$")


async def _resolve_connection(
    db: AsyncSession, user: User, connection_id: str | None
) -> LeagueConnection | None:
    if not connection_id:
        return None
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


async def _load_history(
    db: AsyncSession, user: User, conn: LeagueConnection | None
) -> list[dict[str, str]]:
    query = select(ChatMessage).where(ChatMessage.user_id == user.id)
    # Scope conversation history to the active league so context doesn't bleed
    query = query.where(
        ChatMessage.connection_id == conn.id if conn else ChatMessage.connection_id.is_(None)
    )
    rows = (
        (await db.execute(query.order_by(ChatMessage.created_at.desc()).limit(HISTORY_TURNS)))
        .scalars()
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _should_track_pick(intent: str, context: dict) -> bool:
    return intent == "start_sit" and len(context.get("players") or []) >= 2


def _extract_pick(answer: str) -> tuple[str, str | None]:
    """Strip the trailing 'PICK: <name>' line; return (clean_answer, pick_name)."""
    m = PICK_RE.search(answer)
    if not m:
        return answer, None
    return answer[: m.start()].rstrip(), m.group(1)


async def _store_turn(
    db: AsyncSession,
    user: User,
    conn: LeagueConnection | None,
    question: str,
    answer: str,
    intent: str,
    context: dict,
    pick_name: str | None,
) -> None:
    db.add(
        ChatMessage(
            user_id=user.id,
            connection_id=conn.id if conn else None,
            role="user",
            content=question,
            intent=intent,
        )
    )
    db.add(
        ChatMessage(
            user_id=user.id,
            connection_id=conn.id if conn else None,
            role="assistant",
            content=answer,
            intent=intent,
            context_snapshot=context,
        )
    )

    # Record the start/sit call for the accuracy tracker
    if pick_name:
        players = context.get("players") or []
        pick_lower = pick_name.lower()
        picked = next((p for p in players if p.get("name", "").lower() == pick_lower), None)
        if picked is None:
            picked = next(
                (p for p in players if pick_lower in p.get("name", "").lower()), None
            )
        alternative = next(
            (p for p in players if p.get("id") != (picked or {}).get("id")), None
        )
        if picked and alternative and picked.get("id") and alternative.get("id"):
            week = 1
            try:
                client = SleeperClient()
                try:
                    state = await client.get_nfl_state()
                    week = int(state.get("week") or 1)
                finally:
                    await client.close()
            except Exception:
                logger.warning("Could not fetch NFL week for recommendation tracking")
            db.add(
                Recommendation(
                    user_id=user.id,
                    connection_id=conn.id if conn else None,
                    season=get_settings().current_season,
                    week=week,
                    picked_player_id=picked["id"],
                    alternative_player_id=alternative["id"],
                    scoring_type=(conn.scoring_type if conn else None) or "ppr",
                )
            )

    await db.commit()


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _resolve_connection(db, user, body.connection_id)
    intent, context = await build_context(db, conn, body.message)
    history = await _load_history(db, user, conn)
    track = _should_track_pick(intent, context)

    raw = await generate_response(body.message, context, history, require_pick=track)
    answer, pick_name = _extract_pick(raw) if track else (raw, None)

    await _store_turn(db, user, conn, body.message, answer, intent, context, pick_name)
    return ChatResponse(response=answer, intent=intent, context_used=context)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-sent events: data: {"text": ...} chunks, then data: [DONE]."""
    conn = await _resolve_connection(db, user, body.connection_id)
    intent, context = await build_context(db, conn, body.message)
    history = await _load_history(db, user, conn)
    track = _should_track_pick(intent, context)

    async def event_gen():
        chunks: list[str] = []
        try:
            async for delta in stream_response(
                body.message, context, history, require_pick=track
            ):
                chunks.append(delta)
                yield f"data: {json.dumps({'text': delta})}\n\n"
        except Exception as exc:
            logger.exception("Chat stream failed")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        raw = "".join(chunks)
        answer, pick_name = _extract_pick(raw) if track else (raw, None)
        try:
            await _store_turn(
                db, user, conn, body.message, answer, intent, context, pick_name
            )
        except Exception:
            logger.exception("Failed to store chat turn")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history", response_model=list[ChatHistoryMessage])
async def chat_history(
    limit: int = 50,
    connection_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ChatMessage).where(ChatMessage.user_id == user.id)
    if connection_id:
        try:
            query = query.where(ChatMessage.connection_id == uuid.UUID(connection_id))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid connection id")
    rows = (
        (await db.execute(query.order_by(ChatMessage.created_at.desc()).limit(min(limit, 200))))
        .scalars()
        .all()
    )
    return [
        ChatHistoryMessage(
            role=m.role, content=m.content, intent=m.intent, created_at=m.created_at
        )
        for m in reversed(rows)
    ]
