import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LeagueConnection, Player, Roster, User
from app.services.ai_service import generate_response
from app.services.context_builder import player_package
from app.services.value_service import compute_player_values, side_total
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/trade", tags=["trade"])

TRADE_QUESTION = (
    "Evaluate this trade. The user GIVES the players in trade.give and "
    "RECEIVES the players in trade.receive. Each player has a trade_value "
    "(0-100, percentile of recency-weighted PPR production at their position) "
    "and the totals for each side are in trade.value_summary — anchor your "
    "verdict in those numbers plus the weekly stats.\n\n"
    "Grading rubric (apply strictly):\n"
    "- Value gap under 8 points: even trade — grade both sides in the same "
    "letter band; the verdict hinges on roster fit, not raw value.\n"
    "- Gap 8-19: meaningful edge. Winner gets a full letter grade above loser.\n"
    "- Gap 20+: lopsided. The losing side cannot grade above C, and you should "
    "propose a specific counter using trade.sweetener_candidates if provided.\n"
    "- Positional scarcity matters: an elite RB/TE is worth more than equal "
    "value at WR. Consuming a roster's last startable depth at a position "
    "drops that side half a grade.\n\n"
    "Structure: bold one-line verdict first, then a Side Grades section, then "
    "roster-fit analysis, then a clear ACCEPT / REJECT / COUNTER call with "
    "confidence. If countering, name the exact players to add."
)

# Value gap below which a trade is considered roughly fair
EVEN_THRESHOLD = 8


class TradeRequest(BaseModel):
    connection_id: str
    give: list[str] = Field(min_length=1, max_length=6)
    receive: list[str] = Field(min_length=1, max_length=6)


class TradePlayerValue(BaseModel):
    id: str
    name: str
    value: int
    ppg: float | None = None


class TradeResponse(BaseModel):
    analysis: str
    give_value: int
    receive_value: int
    verdict: str
    player_values: list[TradePlayerValue]
    sweeteners: list[TradePlayerValue]


@router.post("/analyze", response_model=TradeResponse)
async def analyze_trade(
    body: TradeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    scoring_type = conn.scoring_type or "ppr"
    values = await compute_player_values(db)

    name_cache: dict[str, str] = {}

    async def packages(ids: list[str]) -> list[dict]:
        out = []
        for pid in ids:
            player = await db.get(Player, pid)
            if player is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player {pid} not found")
            name_cache[pid] = player.full_name
            pkg = await player_package(db, player, conn.season, scoring_type)
            pkg["trade_value"] = values.get(pid, {}).get("value")
            out.append(pkg)
        return out

    context: dict = {
        "question_type": "trade",
        "league_settings": {
            "platform": conn.platform,
            "league_name": conn.league_name,
            "scoring": scoring_type,
            "roster_positions": conn.roster_positions,
        },
        "trade": {
            "give": await packages(body.give),
            "receive": await packages(body.receive),
        },
    }

    give_value = side_total(values, body.give)
    receive_value = side_total(values, body.receive)
    diff = receive_value - give_value
    if abs(diff) < EVEN_THRESHOLD:
        verdict = "Roughly even trade"
    elif diff > 0:
        verdict = f"You win by {diff} points"
    else:
        verdict = f"You lose by {-diff} points"
    context["trade"]["value_summary"] = {
        "you_give_total": give_value,
        "you_receive_total": receive_value,
        "verdict": verdict,
    }

    # Include the user's roster so depth implications can be judged, and to
    # suggest sweeteners that even out a lopsided trade in the user's favor.
    sweeteners: list[TradePlayerValue] = []
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == conn.team_id
            )
        )
    ).scalar_one_or_none()
    if roster and roster.players:
        players = (
            await db.execute(select(Player).where(Player.id.in_(roster.players)))
        ).scalars().all()
        context["user_roster"] = {
            "players": [
                {
                    "name": p.full_name,
                    "position": p.position,
                    "team": p.team,
                    "trade_value": values.get(p.id, {}).get("value"),
                }
                for p in players
            ]
        }
        if diff >= EVEN_THRESHOLD:
            in_trade = set(body.give) | set(body.receive)
            candidates = [
                (p, values[p.id]["value"])
                for p in players
                if p.id in values and p.id not in in_trade
            ]
            candidates.sort(key=lambda c: abs(c[1] - diff))
            sweeteners = [
                TradePlayerValue(
                    id=p.id,
                    name=p.full_name,
                    value=v,
                    ppg=values[p.id].get("ppg"),
                )
                for p, v in candidates[:3]
            ]
            context["trade"]["sweetener_candidates"] = [
                {"name": s.name, "trade_value": s.value} for s in sweeteners
            ]

    analysis = await generate_response(TRADE_QUESTION, context)
    return TradeResponse(
        analysis=analysis,
        give_value=give_value,
        receive_value=receive_value,
        verdict=verdict,
        player_values=[
            TradePlayerValue(
                id=pid,
                name=name_cache.get(pid, pid),
                value=values.get(pid, {}).get("value", 0),
                ppg=values.get(pid, {}).get("ppg"),
            )
            for pid in [*body.give, *body.receive]
        ],
        sweeteners=sweeteners,
    )
