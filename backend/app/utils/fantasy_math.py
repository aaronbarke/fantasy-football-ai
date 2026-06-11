"""Fantasy point calculations from raw stats, per league scoring settings."""

from typing import Any

# Standard scoring weights keyed by Sleeper scoring_settings field names
DEFAULT_SCORING = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 0.0,  # 1.0 for PPR, 0.5 for half
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
}

# Map our stat column names to Sleeper scoring keys
STAT_TO_SCORING_KEY = {
    "pass_yards": "pass_yd",
    "pass_tds": "pass_td",
    "interceptions": "pass_int",
    "rush_yards": "rush_yd",
    "rush_tds": "rush_td",
    "receptions": "rec",
    "receiving_yards": "rec_yd",
    "receiving_tds": "rec_td",
}


def calculate_points(stats: dict[str, Any], scoring: dict[str, float] | None = None) -> float:
    """Compute fantasy points for a stat line using league scoring settings.

    `stats` uses our player_stats_weekly column names; `scoring` uses Sleeper's
    scoring_settings keys (e.g. {"rec": 1.0, "pass_yd": 0.04}).
    """
    weights = {**DEFAULT_SCORING, **(scoring or {})}
    total = 0.0
    for stat_name, scoring_key in STAT_TO_SCORING_KEY.items():
        value = stats.get(stat_name) or 0
        total += float(value) * weights.get(scoring_key, 0.0)
    return round(total, 2)


def scoring_type_from_settings(scoring_settings: dict[str, Any] | None) -> str:
    """Classify a league as ppr / half_ppr / standard from its reception value."""
    if not scoring_settings:
        return "ppr"
    rec = float(scoring_settings.get("rec", 0) or 0)
    if rec >= 0.75:
        return "ppr"
    if rec >= 0.25:
        return "half_ppr"
    return "standard"


def implied_totals(spread_home: float, over_under: float) -> tuple[float, float]:
    """Implied team totals from the home spread and the game total.

    A home spread of -3.5 means home is favored by 3.5.
    """
    home = over_under / 2 - spread_home / 2
    away = over_under - home
    return round(home, 1), round(away, 1)
