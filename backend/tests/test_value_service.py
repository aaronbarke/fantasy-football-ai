"""Unit tests for the trade-value model's pure pieces."""

from app.services.value_service import (
    ROSTER_FLOOR,
    _blended_base,
    _momentum_adjust,
    _value_from_vor,
    side_total,
)


def test_blended_base_weights_latest_season_and_recent_weeks():
    # latest season (2025) counts 2x the prior; last-4-weeks count double again
    samples = [(2024, 1, 10.0), (2025, 17, 20.0)]  # recent_cutoff=14 -> wk17 doubles
    base = _blended_base(samples, latest_season=2025, recent_cutoff=14)
    # weights: prior 0.5*10=5 ; recent 2.0*20=40 ; /2.5 = 18.0
    assert abs(base - 18.0) < 1e-6


def test_momentum_high_tier_resists_single_bad_week():
    # An elite baseline with one cold game barely moves
    base = 22.0
    recent = [6.0, 23.0, 24.0, 21.0, 22.0]  # one bad most-recent game
    adj = _momentum_adjust(base, recent)
    assert adj < base  # dips
    assert base - adj < 2.0  # but only slightly (tier damp + single-game streak)


def test_momentum_low_tier_not_overrated_by_one_big_game():
    base = 6.0
    recent = [22.0, 5.0, 4.0, 6.0, 5.0]  # one explosion, otherwise low
    adj = _momentum_adjust(base, recent)
    assert adj > base
    assert adj - base < 3.0  # capped — one game doesn't make him a star


def test_momentum_streak_compounds():
    base = 12.0
    one_hot = _momentum_adjust(base, [18.0, 11.0, 12.0, 11.0])
    sustained = _momentum_adjust(base, [18.0, 18.0, 19.0, 18.0])
    assert sustained > one_hot > base  # multiple good weeks move more than one


def test_value_from_vor_has_roster_floor():
    # A player at/under replacement still carries the baseline floor
    assert _value_from_vor(8.0, replacement=10.0) == ROSTER_FLOOR
    # Above replacement scales up
    assert _value_from_vor(20.0, replacement=10.0) > ROSTER_FLOOR


def test_value_carries_one_decimal():
    v = _value_from_vor(15.55, replacement=10.0)
    assert round(v, 1) == v


def test_side_total_sums_and_ignores_unknowns():
    values = {"a": {"value": 30.5}, "b": {"value": 12.0}}
    assert side_total(values, ["a", "b"]) == 42.5
    assert side_total(values, ["a", "ghost"]) == 30.5
