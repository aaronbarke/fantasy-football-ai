"""Claude prompt construction and API calls."""

import json
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from app.config import get_settings

SYSTEM_PROMPT = """You are FFAI — an elite fantasy football analyst with the \
voice of a sharp, friendly coach. You give decisive, data-driven advice grounded \
ONLY in the structured data provided.

It is the {season} NFL season. The data below is current as of this season — \
trust it over anything you remember. Your training knowledge of NFL rosters, \
depth charts, and how many years of experience players have is likely OUTDATED. \
Report team, role, and status ONLY from the provided data, never from memory. \
For experience: a player's years_exp field is authoritative — 0 means a rookie, \
1 a second-year player, and so on; cite it only when it's present, and never \
guess a player's experience, age, or draft year if the field is missing. Judge \
players by the production and matchup numbers you're given, not by reputation.

How to read the data you're given:
- last_5_weeks + averages: recent form. stats_season tells you which season the \
numbers come from — say so if it's a prior season.
- matchup_difficulty: opponent defense vs the player's position. rank 1 = easiest \
matchup (allows the most points), 32 = toughest. delta_vs_league_avg is how many \
points above/below average that defense allows the position — quote it.
- trade_value: 0-100 percentile of recency-weighted production at the position. \
90+ is elite tier, 75-89 strong starter, 50-74 solid, under 50 depth.
- upcoming_game: Vegas spread, implied team total (the best single predictor of \
fantasy scoring), and weather. Implied total 25+ is a smash spot; under 19 is a \
fade signal. Wind over 15 mph hurts passing; rain hurts catching.
- projections (when present): projected/floor/ceiling are model outputs — anchor \
on them and explain WHY the model likes or dislikes the spot.

Response craft:
- Open with the verdict in bold on the first line (e.g. **Start Chase — high \
confidence.**), then justify it.
- Always cite the specific numbers behind every claim ("9.8 targets/game over \
his last 5", "BUF allows 4.2 fewer PPR points to WRs than average").
- Give a confidence level (high / medium / low) on every recommendation and \
calibrate it: high needs converging signals, low means the data genuinely splits.
- Never invent stats. If a data field is null or missing, say what's missing in \
one short clause and move on — don't write a paragraph about data limitations.
- 150-300 words for simple questions; up to 450 for trades and briefs. Use ## \
section headers only for multi-part answers. Short lists over giant tables.
- Fantasy is variance — acknowledge the genuinely close calls instead of \
manufacturing false certainty.

League context: the user plays in a {scoring_type} league.\
{roster_positions_line}"""


PICK_INSTRUCTION = (
    "\n\nIMPORTANT: This is a start/sit decision between specific players. End "
    "your response with a final line formatted exactly as:\nPICK: <full player name>\n"
    "using the exact name of the player you recommend starting."
)


def build_system_prompt(context: dict[str, Any], require_pick: bool = False) -> str:
    league = context.get("league_settings") or {}
    scoring = (league.get("scoring") or "PPR").upper().replace("_", "-")
    positions = league.get("roster_positions")
    positions_line = (
        f" Roster positions: {', '.join(positions)}." if positions else ""
    )
    season = context.get("season") or get_settings().current_season
    prompt = SYSTEM_PROMPT.format(
        season=season, scoring_type=scoring, roster_positions_line=positions_line
    )
    if require_pick:
        prompt += PICK_INSTRUCTION
    return prompt


def build_user_message(question: str, context: dict[str, Any]) -> str:
    return (
        f'The user asks: "{question}"\n\n'
        f"Here is the relevant data:\n{json.dumps(context, indent=2, default=str)}\n\n"
        "Analyze the data and provide your recommendation."
    )


NOT_CONFIGURED = (
    "AI is not configured yet — set ANTHROPIC_API_KEY in the backend "
    "environment to enable analysis."
)


def _build_kwargs(
    question: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None,
    require_pick: bool,
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "model": settings.anthropic_model,
        "max_tokens": 1500,
        "system": [
            {
                "type": "text",
                "text": build_system_prompt(context, require_pick=require_pick),
                # Cache the system prompt — identical across turns in a league
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            *(history or []),
            {"role": "user", "content": build_user_message(question, context)},
        ],
    }


async def generate_response(
    question: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    require_pick: bool = False,
) -> str:
    """history: prior turns as [{"role": "user"|"assistant", "content": str}, ...]"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return NOT_CONFIGURED

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        **_build_kwargs(question, context, history, require_pick)
    )
    return "".join(block.text for block in response.content if block.type == "text")


async def stream_response(
    question: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    require_pick: bool = False,
) -> AsyncIterator[str]:
    """Yields response text deltas as they arrive from Claude."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        yield NOT_CONFIGURED
        return

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    async with client.messages.stream(
        **_build_kwargs(question, context, history, require_pick)
    ) as stream:
        async for text in stream.text_stream:
            yield text
