from fastapi import APIRouter, Depends

from app.models import User
from app.services.ai_service import generate_response
from app.services.betting_service import get_line_board
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/betting", tags=["betting"])

ANALYSIS_QUESTION = (
    "You are looking at a live NFL sportsbook line board (betting.games). For "
    "each game you have the best available moneyline/spread/total across US "
    "books, the range books disagree by, and an edge_score measuring "
    "line-shopping value. Write a concise 'Betting Edge' breakdown: which "
    "games have the most line-shopping value and which book has the best "
    "price, any notable disagreements between books, and how the spreads/"
    "totals relate to fantasy expectations (high totals = fantasy-friendly). "
    "Do NOT promise winners — frame everything as line-shopping and analysis, "
    "and end with a one-line reminder that this is entertainment, not "
    "financial advice."
)


@router.get("/lines")
async def betting_lines(user: User = Depends(get_current_user)):
    return {"games": await get_line_board()}


@router.post("/analysis")
async def betting_analysis(user: User = Depends(get_current_user)):
    board = await get_line_board()
    context = {"question_type": "betting", "betting": {"games": board[:8]}}
    analysis = await generate_response(ANALYSIS_QUESTION, context)
    return {"analysis": analysis}
