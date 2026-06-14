"""Live line shopping across sportsbooks via The Odds API.

One request pulls moneyline/spread/total from every US book. We surface the
best available price on each side and how much books disagree — the "edge"
here is line shopping (a real, factual edge), not picking winners. Results
are cached to respect the free-tier request budget.
"""

import logging

import httpx

from app.config import get_settings
from app.services.cache import cache_get, cache_set
from app.utils.constants import TEAM_NAME_TO_ABBR

logger = logging.getLogger(__name__)

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
CACHE_KEY = "betting:lines"
CACHE_TTL = 600  # 10 min — plenty fresh for line shopping

# Legal, state-regulated US sportsbooks. We restrict the board to these so the
# best prices and arbitrage come from books a US user can actually bet at —
# offshore/grey-market books (Bovada, MyBookie, LowVig, BetOnline) are excluded.
REGULATED_BOOKS = {
    "DraftKings",
    "FanDuel",
    "BetMGM",
    "Caesars",
    "BetRivers",
    "ESPN BET",
    "Fanatics",
    "Bally Bet",
    "Hard Rock Bet",
    "WynnBET",
    "Fliff",
    "betPARX",
}


def _regulated(bookmakers: list[dict]) -> list[dict]:
    """Keep only regulated US books; fall back to all if none match."""
    legal = [b for b in bookmakers if b.get("title") in REGULATED_BOOKS]
    return legal or bookmakers


def _american_to_prob(price: int) -> float:
    """Implied probability of an American-odds price (no-vig not applied)."""
    return 100 / (price + 100) if price > 0 else (-price) / (-price + 100)


def _moneyline_arbitrage(
    home: str, away: str, home_ml: dict | None, away_ml: dict | None
) -> dict | None:
    """A guaranteed-profit opportunity exists when the best price on each side
    has implied probabilities summing to under 100%."""
    if not home_ml or not away_ml:
        return None
    hp = _american_to_prob(home_ml["best"]["price"])
    ap = _american_to_prob(away_ml["best"]["price"])
    total = hp + ap
    if total >= 1.0:
        return None
    return {
        "profit_pct": round((1.0 / total - 1.0) * 100, 2),
        "home": {
            "team": home,
            "book": home_ml["best"]["book"],
            "price": home_ml["best"]["price"],
            "stake_pct": round(hp / total * 100, 1),
        },
        "away": {
            "team": away,
            "book": away_ml["best"]["book"],
            "price": away_ml["best"]["price"],
            "stake_pct": round(ap / total * 100, 1),
        },
    }


async def fetch_full_odds() -> list[dict]:
    settings = get_settings()
    if not settings.odds_api_key:
        return []
    params = {
        "apiKey": settings.odds_api_key,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ODDS_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def _best_price(entries: list[dict]) -> dict | None:
    """Highest american odds = best payout for the bettor."""
    if not entries:
        return None
    return max(entries, key=lambda e: e["price"])


def build_line_board(games: list[dict]) -> list[dict]:
    board = []
    for game in games:
        home_name = game.get("home_team", "")
        away_name = game.get("away_team", "")
        home = TEAM_NAME_TO_ABBR.get(home_name)
        away = TEAM_NAME_TO_ABBR.get(away_name)
        if not home or not away:
            continue

        ml: dict[str, list[dict]] = {home: [], away: []}
        spreads: dict[str, list[dict]] = {home: [], away: []}
        totals: dict[str, list[dict]] = {"Over": [], "Under": []}

        for book in _regulated(game.get("bookmakers", [])):
            book_name = book.get("title", book.get("key", "?"))
            for market in book.get("markets", []):
                for o in market.get("outcomes", []):
                    name = o.get("name", "")
                    price = o.get("price")
                    if price is None:
                        continue
                    entry = {"book": book_name, "price": int(price)}
                    if market["key"] == "h2h":
                        side = home if name == home_name else away if name == away_name else None
                        if side:
                            ml[side].append(entry)
                    elif market["key"] == "spreads":
                        side = home if name == home_name else away if name == away_name else None
                        if side and o.get("point") is not None:
                            spreads[side].append({**entry, "point": float(o["point"])})
                    elif market["key"] == "totals" and name in totals:
                        if o.get("point") is not None:
                            totals[name].append({**entry, "point": float(o["point"])})

        def spread_summary(side: str) -> dict | None:
            entries = spreads[side]
            if not entries:
                return None
            # Best = most points in your favor; tiebreak on price
            best = max(entries, key=lambda e: (e["point"], e["price"]))
            points = [e["point"] for e in entries]
            return {"best": best, "range": [min(points), max(points)], "books": len(entries)}

        def ml_summary(side: str) -> dict | None:
            entries = ml[side]
            if not entries:
                return None
            best = _best_price(entries)
            prices = [e["price"] for e in entries]
            return {
                "best": best,
                "worst_price": min(prices),
                "books": len(entries),
                # Price spread across books in american-odds points
                "shop_value": best["price"] - min(prices),
            }

        def total_summary(side: str) -> dict | None:
            entries = totals[side]
            if not entries:
                return None
            # Over: lower line is better; Under: higher line is better
            best = (
                min(entries, key=lambda e: (e["point"], -e["price"]))
                if side == "Over"
                else max(entries, key=lambda e: (e["point"], e["price"]))
            )
            points = [e["point"] for e in entries]
            return {"best": best, "range": [min(points), max(points)], "books": len(entries)}

        home_spread = spread_summary(home)
        away_spread = spread_summary(away)
        home_ml = ml_summary(home)
        away_ml = ml_summary(away)

        edge_score = 0.0
        for s in (home_spread, away_spread):
            if s:
                edge_score += (s["range"][1] - s["range"][0]) * 10
        for m in (home_ml, away_ml):
            if m:
                edge_score += m["shop_value"]

        arbitrage = _moneyline_arbitrage(home, away, home_ml, away_ml)

        board.append(
            {
                "home_team": home,
                "away_team": away,
                "commence_time": game.get("commence_time"),
                "moneyline": {home: home_ml, away: away_ml},
                "spread": {home: home_spread, away: away_spread},
                "total": {"over": total_summary("Over"), "under": total_summary("Under")},
                "edge_score": round(edge_score, 1),
                "arbitrage": arbitrage,
            }
        )

    # Arbitrage games first (by profit), then by line-shopping disagreement.
    board.sort(
        key=lambda g: (
            g["arbitrage"] is None,
            -(g["arbitrage"]["profit_pct"] if g["arbitrage"] else 0.0),
            -g["edge_score"],
        )
    )
    return board


async def get_line_board() -> list[dict]:
    cached = await cache_get(CACHE_KEY)
    if cached is not None:
        return cached
    games = await fetch_full_odds()
    board = build_line_board(games)
    if board:
        await cache_set(CACHE_KEY, board, CACHE_TTL)
    return board
