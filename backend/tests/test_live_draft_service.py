from app.services.live_draft_service import _parse_picks


def _slot(overall, team, rnd, round_pick, player_id=-1):
    return {
        "overallPickNumber": overall,
        "teamId": team,
        "roundId": rnd,
        "roundPickNumber": round_pick,
        "playerId": player_id,
    }


# ESPN player id -> our canonical (Sleeper) id
ESPN_MAP = {"4429795": "gibbs", "4430807": "bijan", "4426515": "nacua"}


class TestParsePicks:
    def test_undrafted_board_has_no_made_picks(self):
        raw = [_slot(i + 1, (i % 12) + 1, 1, i + 1) for i in range(12)]
        out = _parse_picks(raw, ESPN_MAP, my_team="3")
        assert out["picks_made"] == 0
        assert out["drafted_player_ids"] == []
        assert out["on_the_clock"]["overall_pick"] == 1

    def test_maps_made_picks_to_our_player_ids(self):
        raw = [
            _slot(1, 4, 1, 1, player_id=4429795),  # Gibbs
            _slot(2, 3, 1, 2, player_id=4430807),  # Bijan — your team
            _slot(3, 7, 1, 3),  # not yet picked
        ]
        out = _parse_picks(raw, ESPN_MAP, my_team="3")
        assert out["picks_made"] == 2
        assert out["drafted_player_ids"] == ["gibbs", "bijan"]
        assert out["your_player_ids"] == ["bijan"]  # only your team's pick
        assert out["on_the_clock"]["overall_pick"] == 3

    def test_detects_your_draft_slot_from_round_one(self):
        raw = [_slot(i + 1, (i % 12) + 1, 1, i + 1) for i in range(12)]
        # team 3 sits at round-1 pick 3
        out = _parse_picks(raw, ESPN_MAP, my_team="3")
        assert out["your_slot"] == 3

    def test_unmapped_pick_is_counted_not_dropped(self):
        raw = [_slot(1, 4, 1, 1, player_id=999999)]  # unknown ESPN id
        out = _parse_picks(raw, ESPN_MAP, my_team="3")
        assert out["picks_made"] == 1
        assert out["unmapped_count"] == 1
        assert out["drafted_player_ids"] == []  # nothing to mark off the board

    def test_completed_draft_has_no_one_on_the_clock(self):
        raw = [
            _slot(1, 4, 1, 1, player_id=4429795),
            _slot(2, 3, 1, 2, player_id=4430807),
        ]
        out = _parse_picks(raw, ESPN_MAP, my_team="3")
        assert out["on_the_clock"] is None

    def test_no_team_id_means_nothing_is_yours(self):
        raw = [_slot(1, 4, 1, 1, player_id=4429795)]
        out = _parse_picks(raw, ESPN_MAP, my_team=None)
        assert out["your_player_ids"] == []
        assert out["your_slot"] is None
