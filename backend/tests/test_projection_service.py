import math

from app.services.gameplan_service import optimize_lineup
from app.services.projection_service import win_probability


def _player(pid, pos, proj):
    return {"id": pid, "name": pid, "position": pos, "projected": proj}


def test_win_probability_even_matchup():
    assert abs(win_probability(120, 100, 120, 100) - 0.5) < 1e-6


def test_win_probability_favored_team():
    p = win_probability(130, 100, 110, 100)
    assert 0.85 < p < 1.0
    # Symmetry: the underdog gets the complement
    assert abs(p + win_probability(110, 100, 130, 100) - 1.0) < 1e-9


def test_win_probability_bounded():
    assert 0.0 <= win_probability(200, 50, 80, 50) <= 1.0
    assert math.isclose(
        win_probability(100, 0, 100, 0), 0.5, abs_tol=1e-6
    )


def test_optimize_lineup_fills_fixed_slots_best_first():
    players = [
        _player("qb1", "QB", 22),
        _player("qb2", "QB", 18),
        _player("rb1", "RB", 17),
        _player("rb2", "RB", 14),
        _player("rb3", "RB", 12),
        _player("wr1", "WR", 16),
        _player("wr2", "WR", 11),
        _player("te1", "TE", 9),
    ]
    lineup, bench = optimize_lineup(
        ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"], players
    )
    by_slot = {}
    for s in lineup:
        by_slot.setdefault(s["slot"], []).append(s["player"]["id"] if s["player"] else None)
    assert by_slot["QB"] == ["qb1"]
    assert set(by_slot["RB"]) == {"rb1", "rb2"}
    assert set(by_slot["WR"]) == {"wr1", "wr2"}
    # FLEX takes the best remaining RB/WR/TE — rb3
    assert by_slot["FLEX"] == ["rb3"]
    assert {p["id"] for p in bench} == {"qb2"}


def test_optimize_lineup_handles_missing_position():
    players = [_player("wr1", "WR", 15)]
    lineup, bench = optimize_lineup(["QB", "WR", "FLEX"], players)
    slots = {s["slot"]: s["player"] for s in lineup}
    assert slots["QB"] is None
    assert slots["WR"]["id"] == "wr1"
    assert slots["FLEX"] is None
    assert bench == []
