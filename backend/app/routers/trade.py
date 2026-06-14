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
    "RECEIVES the players in trade.receive. Each player has a trade_value — a "
    "single value number from Value Over Replacement (higher = more valuable; "
    "elite players run 40-70+, startable contributors 15-35, depth under 10). "
    "Some players also carry a trend (rising/falling) from recent "
    "form. trade.value_summary has each side's total and the gap as a percent "
    "of the larger side — anchor your verdict in those numbers plus the stats.\n\n"
    "Grading rubric (apply strictly, judged by the GAP %):\n"
    "- Gap under 8%: even trade — grade both sides in the same letter band; the "
    "verdict hinges on roster fit, not raw value.\n"
    "- Gap 8-20%: meaningful edge. Winner gets a full letter grade above loser.\n"
    "- Gap over 20%: lopsided. The losing side cannot grade above C, and you "
    "should propose a specific counter using trade.sweetener_candidates.\n"
    "- Positional scarcity is already priced into the values (VOR), so trust the "
    "totals; still flag when a trade guts a roster's last startable depth at a "
    "position, and weigh a rising/falling trend when the call is close.\n\n"
    "Structure: bold one-line verdict first, then a Side Grades section, then "
    "roster-fit analysis, then a clear ACCEPT / REJECT / COUNTER call with "
    "confidence. If countering, name the exact players to add."
)

# Gap (as a fraction of the larger side) below which a trade is roughly fair
EVEN_GAP_PCT = 0.08


class TradeRequest(BaseModel):
    connection_id: str
    give: list[str] = Field(min_length=1, max_length=6)
    receive: list[str] = Field(min_length=1, max_length=6)


class TradePlayerValue(BaseModel):
    id: str
    name: str
    value: float
    ppg: float | None = None
    trend: str | None = None


class TradeResponse(BaseModel):
    analysis: str
    give_value: float
    receive_value: float
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
    bigger = max(give_value, receive_value, 1)
    gap_pct = abs(diff) / bigger
    if gap_pct < EVEN_GAP_PCT:
        verdict = "Roughly even trade"
    elif diff > 0:
        verdict = f"You win by {diff:.1f}"
    else:
        verdict = f"You lose by {-diff:.1f}"
    context["trade"]["value_summary"] = {
        "you_give_total": give_value,
        "you_receive_total": receive_value,
        "gap": abs(diff),
        "gap_pct": round(gap_pct * 100, 1),
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
        if diff > 0 and gap_pct >= EVEN_GAP_PCT:
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
                    trend=values[p.id].get("trend"),
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
                trend=values.get(pid, {}).get("trend"),
            )
            for pid in [*body.give, *body.receive]
        ],
        sweeteners=sweeteners,
    )
