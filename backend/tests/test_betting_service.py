"""Unit tests for line-shopping + arbitrage logic."""

from app.services.betting_service import (
    _american_to_prob,
    _moneyline_arbitrage,
    _regulated,
)


def test_american_to_prob():
    assert abs(_american_to_prob(100) - 0.5) < 1e-9
    assert abs(_american_to_prob(-200) - (200 / 300)) < 1e-9
    assert abs(_american_to_prob(150) - (100 / 250)) < 1e-9


def test_arbitrage_detected_when_probs_under_one():
    # +120 / +120 -> 0.4545*2 = 0.909 < 1 -> ~10% arb, 50/50 stakes
    arb = _moneyline_arbitrage(
        "HOME", "AWAY",
        {"best": {"price": 120, "book": "DraftKings"}},
        {"best": {"price": 120, "book": "FanDuel"}},
    )
    assert arb is not None
    assert abs(arb["profit_pct"] - 10.0) < 0.1
    assert abs(arb["home"]["stake_pct"] - 50.0) < 0.1


def test_no_arbitrage_with_normal_vig():
    arb = _moneyline_arbitrage(
        "H", "A",
        {"best": {"price": -200, "book": "x"}},
        {"best": {"price": 150, "book": "y"}},
    )
    assert arb is None


def test_arbitrage_none_when_a_side_missing():
    assert _moneyline_arbitrage("H", "A", None, {"best": {"price": 120, "book": "x"}}) is None


def test_regulated_filters_offshore_but_falls_back():
    books = [
        {"title": "DraftKings"},
        {"title": "Bovada"},
        {"title": "MyBookie.ag"},
    ]
    legal = _regulated(books)
    assert {b["title"] for b in legal} == {"DraftKings"}
    # If nothing is regulated, fall back to all rather than blanking the game
    offshore_only = [{"title": "Bovada"}, {"title": "LowVig.ag"}]
    assert _regulated(offshore_only) == offshore_only
