"""ESPN live-score extraction: prefer totalPointsLive, else sum the live
roster's applied points, else the final total."""

from app.services.sync_service import _espn_points


def test_prefers_total_points_live():
    assert _espn_points({"totalPointsLive": 63.4, "totalPoints": 0}) == 63.4


def test_sums_starters_when_no_live_total():
    side = {
        "totalPoints": 0,
        "rosterForCurrentScoringPeriod": {
            "entries": [
                {"lineupSlotId": 0, "playerPoolEntry": {"appliedStatTotal": 20.0}},
                {"lineupSlotId": 2, "playerPoolEntry": {"appliedStatTotal": 12.5}},
                {"lineupSlotId": 20, "playerPoolEntry": {"appliedStatTotal": 99.0}},  # bench
                {"lineupSlotId": 21, "playerPoolEntry": {"appliedStatTotal": 5.0}},   # IR
            ]
        },
    }
    assert _espn_points(side) == 32.5  # starters only, bench/IR excluded


def test_falls_back_to_final_total():
    assert _espn_points({"totalPoints": 118.2}) == 118.2
    assert _espn_points({}) == 0.0
