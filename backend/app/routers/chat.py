import json
import logging
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ChatMessage, LeagueConnection, Recommendation, User
from app.schemas.chat import ChatHistoryMessage, ChatRequest, ChatResponse
from app.services.ai_service import generate_response, stream_response
from app.services.context_builder import build_context
from app.services.sleeper_service import SleeperClient
from app.utils.security import ai_quota, get_current_user, is_demo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_TURNS = 8  # prior messages included for conversation continuity

PICK_RE = re.compile(r"\n?PICK:\s*(.+?)\s*$")

# Every demo visitor signs into the same account, so demo conversations can't
# live in the shared chat_messages rows (each visitor would read — and feed the
# AI — everyone else's questions). They're kept in memory per demo session
# (the token's `sid`) and league instead, and dropped oldest-first.
DEMO_SESSIONS_MAX = 2000
DEMO_MESSAGES_MAX = 50
_demo_chats: "OrderedDict[str, list[dict]]" = OrderedDict()


def _demo_key(request: Request, user: User, connection_id: str | None) -> str | None:
    """Memory key for a demo visitor's thread in one league; None for real
    accounts (their history is in the database) or a demo token without a
    session id (nothing to scope it to, so it gets no history)."""
    if not is_demo(user):
        return None
    sid = (getattr(request.state, "token_claims", None) or {}).get("sid")
    return f"{sid}:{connection_id or ''}" if sid else None


def _demo_messages(key: str | None) -> list[dict]:
    if key is None or key not in _demo_chats:
        return []
    _demo_chats.move_to_end(key)
    return _demo_chats[key]


def _demo_append(key: str | None, question: str, answer: str, intent: str) -> None:
    if key is None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    thread = _demo_chats.setdefault(key, [])
    _demo_chats.move_to_end(key)
    thread.extend(
        [
            {"role": "user", "content": question, "intent": intent, "created_at": now},
            {"role": "assistant", "content": answer, "intent": intent, "created_at": now},
        ]
    )
    del thread[:-DEMO_MESSAGES_MAX]
    while len(_demo_chats) > DEMO_SESSIONS_MAX:
        _demo_chats.popitem(last=False)


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
    db: AsyncSession, user: User, conn: LeagueConnection | None, demo_key: str | None = None
) -> list[dict[str, str]]:
    if is_demo(user):
        return [
            {"role": m["role"], "content": m["content"]}
            for m in _demo_messages(demo_key)[-HISTORY_TURNS:]
        ]
    query = select(ChatMessage).where(ChatMessage.user_id == user.id)
    # Scope conversation history to the active league so context doesn't bleed
    query = query.where(
        ChatMessage.connection_id == conn.id if conn else ChatMessage.connection_id.is_(None)
    )
    rows = (
        # A turn's question and answer share one timestamp, so the id keeps
        # them in order.
        (
            await db.execute(
                query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(
                    HISTORY_TURNS
                )
            )
        )
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
    demo_key: str | None = None,
) -> None:
    if is_demo(user):
        # Not persisted: see _demo_chats. The accuracy tracker is skipped too,
        # since its record would be shared by every demo visitor.
        _demo_append(demo_key, question, answer, intent)
        return
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
                    season=conn.season if conn else get_settings().current_season,
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
    request: Request,
    user: User = Depends(ai_quota),
    db: AsyncSession = Depends(get_db),
):
    conn = await _resolve_connection(db, user, body.connection_id)
    demo_key = _demo_key(request, user, str(conn.id) if conn else None)
    intent, context = await build_context(db, conn, body.message)
    history = [] if body.fresh else await _load_history(db, user, conn, demo_key)
    track = _should_track_pick(intent, context)

    raw = await generate_response(body.message, context, history, require_pick=track)
    answer, pick_name = _extract_pick(raw) if track else (raw, None)

    await _store_turn(
        db, user, conn, body.message, answer, intent, context, pick_name, demo_key
    )
    return ChatResponse(response=answer, intent=intent, context_used=context)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: User = Depends(ai_quota),
    db: AsyncSession = Depends(get_db),
):
    """Server-sent events: data: {"text": ...} chunks, then data: [DONE]."""
    conn = await _resolve_connection(db, user, body.connection_id)
    demo_key = _demo_key(request, user, str(conn.id) if conn else None)
    intent, context = await build_context(db, conn, body.message)
    history = [] if body.fresh else await _load_history(db, user, conn, demo_key)
    track = _should_track_pick(intent, context)

    async def event_gen():
        chunks: list[str] = []
        try:
            async for delta in stream_response(
                body.message, context, history, require_pick=track
            ):
                chunks.append(delta)
                yield f"data: {json.dumps({'text': delta})}\n\n"
        except Exception:
            # Details go to the log, not the browser (they can name upstream
            # accounts, request ids and quota state).
            logger.exception("Chat stream failed")
            message = "The AI service hit an error — try again in a moment."
            yield f"data: {json.dumps({'error': message})}\n\n"
            return

        raw = "".join(chunks)
        answer, pick_name = _extract_pick(raw) if track else (raw, None)
        try:
            await _store_turn(
                db, user, conn, body.message, answer, intent, context, pick_name, demo_key
            )
        except Exception:
            logger.exception("Failed to store chat turn")
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_connection_id(connection_id: str | None) -> uuid.UUID | None:
    if not connection_id:
        return None
    try:
        return uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid connection id")


@router.get("/history", response_model=list[ChatHistoryMessage])
async def chat_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    connection_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = _parse_connection_id(connection_id)
    if is_demo(user):
        thread = _demo_messages(_demo_key(request, user, str(cid) if cid else None))
        return [ChatHistoryMessage(**m) for m in thread[-limit:]]
    query = select(ChatMessage).where(ChatMessage.user_id == user.id)
    if cid:
        query = query.where(ChatMessage.connection_id == cid)
    rows = (
        (
            await db.execute(
                query.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(
                    limit
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        ChatHistoryMessage(
            role=m.role, content=m.content, intent=m.intent, created_at=m.created_at
        )
        for m in reversed(rows)
    ]


@router.delete("/history", status_code=204)
async def clear_history(
    request: Request,
    connection_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = _parse_connection_id(connection_id)
    if is_demo(user):
        # Only this visitor's own threads — never the shared account's rows.
        prefix = _demo_key(request, user, str(cid) if cid else None)
        if prefix is not None:
            if cid:
                _demo_chats.pop(prefix, None)
            else:
                for key in [k for k in _demo_chats if k.startswith(prefix)]:
                    del _demo_chats[key]
        return
    stmt = delete(ChatMessage).where(ChatMessage.user_id == user.id)
    if cid:
        stmt = stmt.where(ChatMessage.connection_id == cid)
    await db.execute(stmt)
    await db.commit()
