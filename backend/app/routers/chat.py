import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ChatMessage, LeagueConnection, User
from app.schemas.chat import ChatHistoryMessage, ChatRequest, ChatResponse
from app.services.ai_service import generate_response
from app.services.context_builder import build_context
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_TURNS = 8  # prior messages included for conversation continuity


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn: LeagueConnection | None = None
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

    intent, context = await build_context(db, conn, body.message)

    history_rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(HISTORY_TURNS)
            )
        )
        .scalars()
        .all()
    )
    history = [
        {"role": m.role, "content": m.content} for m in reversed(history_rows)
    ]

    answer = await generate_response(body.message, context, history)

    db.add(
        ChatMessage(
            user_id=user.id,
            connection_id=conn.id if conn else None,
            role="user",
            content=body.message,
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
    await db.commit()

    return ChatResponse(response=answer, intent=intent, context_used=context)


@router.get("/history", response_model=list[ChatHistoryMessage])
async def chat_history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.user_id == user.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(min(limit, 200))
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
