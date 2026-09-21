"""ESPN team D/ST resolve to our team-code defense ids (they aren't in the
player id crosswalk)."""

from app.services.espn_service import ESPNClient, espn_defense_code


def _entry(pos_id, pro_team, slot=16, pts=None):
    ppe = {"player": {"defaultPositionId": pos_id, "proTeamId": pro_team}}
    if pts is not None:
        ppe["appliedStatTotal"] = pts
    return {"lineupSlotId": slot, "playerPoolEntry": ppe}


def test_espn_defense_code():
    assert espn_defense_code(_entry(16, 25)) == "SF"
    assert espn_defense_code(_entry(16, 28)) == "WAS"  # ESPN WSH -> our WAS
    assert espn_defense_code(_entry(1, 25)) is None     # a QB, not a D/ST
    assert espn_defense_code(_entry(16, 999)) is None   # unknown pro team


def test_parse_defenses_started_vs_bench():
    team = {
        "roster": {
            "entries": [
                _entry(16, 25, slot=16),   # SF, started
                _entry(16, 26, slot=20),   # SEA, bench
                _entry(2, 25, slot=2),     # an RB, ignored
            ]
        }
    }
    all_def, starters = ESPNClient.parse_defenses(team)
    assert all_def == ["SF", "SEA"]
    assert starters == ["SF"]
