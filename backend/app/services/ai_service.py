"""Claude prompt construction and API calls."""

import json
from typing import Any

from anthropic import AsyncAnthropic

from app.config import get_settings

SYSTEM_PROMPT = """You are a fantasy football analyst assistant. You give specific, \
data-driven advice based on the structured data provided.

Rules:
- Always cite specific stats when making claims (e.g., "Chase has averaged 9.8 \
targets per game over his last 5")
- Factor in: recent performance trends (last 3-5 weeks weighted heavier than season \
average), matchup difficulty, game script (implied team total and spread), weather \
conditions, and injury status
- For start/sit questions, give a clear recommendation with a confidence level \
(high / medium / low)
- Never make up stats. If data is missing from the context, say so explicitly.
- Acknowledge uncertainty — fantasy is inherently unpredictable
- Keep responses concise but thorough: 150-300 words is typical
- Format key stats readably (short lists are fine; avoid giant tables)

League context: the user plays in a {scoring_type} league.\
{roster_positions_line}"""


def build_system_prompt(context: dict[str, Any]) -> str:
    league = context.get("league_settings") or {}
    scoring = (league.get("scoring") or "PPR").upper().replace("_", "-")
    positions = league.get("roster_positions")
    positions_line = (
        f" Roster positions: {', '.join(positions)}." if positions else ""
    )
    return SYSTEM_PROMPT.format(
        scoring_type=scoring, roster_positions_line=positions_line
    )


def build_user_message(question: str, context: dict[str, Any]) -> str:
    return (
        f'The user asks: "{question}"\n\n'
        f"Here is the relevant data:\n{json.dumps(context, indent=2, default=str)}\n\n"
        "Analyze the data and provide your recommendation."
    )


async def generate_response(
    question: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> str:
    """history: prior turns as [{"role": "user"|"assistant", "content": str}, ...]"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return (
            "AI is not configured yet — set ANTHROPIC_API_KEY in the backend "
            "environment to enable analysis."
        )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages = [
        *(history or []),
        {"role": "user", "content": build_user_message(question, context)},
    ]
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": build_system_prompt(context),
                # Cache the system prompt — identical across turns in a league
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    return "".join(block.text for block in response.content if block.type == "text")
