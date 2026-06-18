"""Weather adjustment, trade grading, and Game Plan helpers."""

from types import SimpleNamespace

from app.routers.trade import grade_trade
from app.services.gameplan_service import (
    _all_lineup_slots,
    _display_lineup,
    _edge_reason,
)
from app.services.projection_service import _weather_adjust


def _gc(**kw):
    defaults = {"wind_mph": 0, "precipitation_pct": 0, "dome": False}
    return SimpleNamespace(**{**defaults, **kw})


def test_weather_neutral_indoors_or_calm():
    assert _weather_adjust("WR", 15.0, _gc(dome=True)) == 0.0
    assert _weather_adjust("WR", 15.0, _gc(wind_mph=5)) == 0.0
    assert _weather_adjust("WR", 15.0, None) == 0.0


def test_weather_high_wind_hurts_passing_helps_run():
    base = 15.0
    assert _weather_adjust("QB", base, _gc(wind_mph=25)) < 0
    assert _weather_adjust("WR", base, _gc(wind_mph=25)) < 0
    assert _weather_adjust("RB", base, _gc(wind_mph=25)) >= 0


def test_weather_adjustment_capped():
    # Even a monsoon can't swing more than the cap
    adj = _weather_adjust("WR", 20.0, _gc(wind_mph=60, precipitation_pct=100))
    assert adj >= -0.12 * 20.0 - 1e-9


def test_grade_trade_even_within_threshold():
    verdict, diff, gap = grade_trade(100.0, 105.0)  # 5% gap < 8%
    assert verdict == "Roughly even trade"
    assert diff == 5.0


def test_grade_trade_win_and_loss():
    v, diff, _ = grade_trade(50.0, 70.0)
    assert v.startswith("You win by") and diff == 20.0
    v2, diff2, _ = grade_trade(70.0, 50.0)
    assert v2.startswith("You lose by") and diff2 == -20.0


def test_all_lineup_slots_keeps_kdef_and_normalizes():
    conn = SimpleNamespace(roster_positions=["QB", "RB", "WR", "FLEX", "K", "D/ST", "BN"])
    slots = _all_lineup_slots(conn)
    assert "K" in slots and "DEF" in slots  # D/ST normalized to DEF
    assert "BN" not in slots  # bench excluded


def test_display_lineup_fills_kdef_from_roster():
    all_slots = ["QB", "RB", "K", "DEF"]
    cards = [
        {"id": "1", "name": "QB1", "position": "QB", "projected": 20.0},
        {"id": "2", "name": "RB1", "position": "RB", "projected": 15.0},
        {"id": "3", "name": "K1", "position": "K", "projected": None},
        {"id": "4", "name": "DEF1", "position": "DEF", "projected": None},
    ]
    rows = _display_lineup(all_slots, cards)
    slots = [r["slot"] for r in rows]
    assert slots == ["QB", "RB", "K", "DEF"]
    assert rows[2]["player"]["name"] == "K1"
    assert rows[3]["player"]["name"] == "DEF1"


def test_edge_reason_picks_strongest_factor():
    start = {"weather_adj": 1.5, "vegas_adj": 0.2, "matchup_adj": 0.1}
    sit = {"weather_adj": -0.5, "vegas_adj": 0.1, "matchup_adj": 0.0}
    assert _edge_reason(start, sit) == "weather"
    # No meaningful edge -> None
    assert _edge_reason({"weather_adj": 0}, {"weather_adj": 0}) is None
