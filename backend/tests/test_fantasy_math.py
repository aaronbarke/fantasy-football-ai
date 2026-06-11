from app.utils.fantasy_math import (
    calculate_points,
    implied_totals,
    scoring_type_from_settings,
)


def test_ppr_scoring():
    stats = {
        "receptions": 8,
        "receiving_yards": 132,
        "receiving_tds": 1,
        "rush_yards": 0,
    }
    points = calculate_points(stats, {"rec": 1.0})
    # 8 rec + 13.2 yds + 6 td = 27.2
    assert points == 27.2


def test_standard_scoring_ignores_receptions():
    stats = {"receptions": 8, "receiving_yards": 100}
    assert calculate_points(stats, {"rec": 0.0}) == 10.0


def test_qb_scoring():
    stats = {"pass_yards": 300, "pass_tds": 3, "interceptions": 1}
    # 12 + 12 - 2 = 22
    assert calculate_points(stats, {}) == 22.0


def test_custom_pass_td_value():
    stats = {"pass_yards": 0, "pass_tds": 2}
    assert calculate_points(stats, {"pass_td": 6.0}) == 12.0


def test_scoring_type_classification():
    assert scoring_type_from_settings({"rec": 1.0}) == "ppr"
    assert scoring_type_from_settings({"rec": 0.5}) == "half_ppr"
    assert scoring_type_from_settings({"rec": 0.0}) == "standard"
    assert scoring_type_from_settings(None) == "ppr"


def test_implied_totals():
    # Home favored by 3.5, total 47.5 → home 25.5, away 22.0
    home, away = implied_totals(-3.5, 47.5)
    assert home == 25.5
    assert away == 22.0
    assert home + away == 47.5
