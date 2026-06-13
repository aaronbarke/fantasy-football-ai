from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    connection_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    # Quick-ask deep links from other pages set this so the answer starts a
    # clean thread instead of inheriting the running conversation.
    fresh: bool = False


class ChatResponse(BaseModel):
    response: str
    intent: str
    context_used: dict[str, Any] | None = None


class ChatHistoryMessage(BaseModel):
    role: str
    content: str
    intent: str | None
    created_at: datetime
