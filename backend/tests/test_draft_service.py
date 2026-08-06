from collections import Counter

from app.services.draft_service import (
    MAX_TIERS,
    _adp_implied,
    _assign_tiers,
    _blend,
    _lineup_value,
    _recommend_cap,
    _roster_slots,
    _status_adjust,
    availability_at,
    recommend_picks,
    replacement_ranks,
    starters_per_team,
)

STANDARD = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN", "IR"]
SUPERFLEX = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF"]


class TestStartersPerTeam:
    def test_direct_slots_counted(self):
        starters = starters_per_team(STANDARD)
        assert starters["QB"] == 1.0
        assert starters["K"] == 1.0

    def test_flex_is_spread_not_assigned_to_one_position(self):
        starters = starters_per_team(STANDARD)
        # 2 dedicated RB + a share of the single FLEX
        assert 2.0 < starters["RB"] < 3.0
        assert 2.0 < starters["WR"] < 3.0
        assert 1.0 < starters["TE"] < 2.0
        flex_total = (
            starters["RB"] - 2 + starters["WR"] - 2 + starters["TE"] - 1
        )
        assert flex_total == 1.0  # one flex slot, fully distributed

    def test_bench_and_ir_ignored(self):
        assert starters_per_team(STANDARD) == starters_per_team(
            [s for s in STANDARD if s not in ("BN", "IR")]
        )

    def test_superflex_raises_qb_demand(self):
        assert starters_per_team(SUPERFLEX)["QB"] > starters_per_team(STANDARD)["QB"]

    def test_none_falls_back_to_a_default_roster(self):
        assert starters_per_team(None)["QB"] == 1.0


class TestReplacementRanks:
    def test_scales_with_league_size(self):
        ten = replacement_ranks(STANDARD, 10)
        fourteen = replacement_ranks(STANDARD, 14)
        for pos in ("QB", "RB", "WR", "TE"):
            assert fourteen[pos] > ten[pos]

    def test_superflex_pushes_qb_replacement_much_deeper(self):
        # The whole point of superflex: QBs stop being interchangeable.
        assert (
            replacement_ranks(SUPERFLEX, 12)["QB"]
            > replacement_ranks(STANDARD, 12)["QB"] + 4
        )

    def test_never_zero(self):
        assert all(rank >= 1 for rank in replacement_ranks(STANDARD, 4).values())


class TestAvailabilityAt:
    def test_even_odds_at_his_own_adp(self):
        assert availability_at(25, 6, 25) == 0.5

    def test_monotonically_decreases_as_your_pick_gets_later(self):
        probs = [availability_at(25, 6, p) for p in (10, 20, 25, 30, 40)]
        assert probs == sorted(probs, reverse=True)

    def test_bounded_to_a_probability(self):
        for pick in (1, 25, 300):
            assert 0.0 <= availability_at(25, 6, pick) <= 1.0

    def test_tight_adp_is_more_certain_than_volatile_adp(self):
        # Same player, same pick — a wider draft range means more uncertainty.
        assert availability_at(25, 1, 30) < availability_at(25, 12, 30)

    def test_without_stdev_degrades_to_before_or_after(self):
        assert availability_at(25, None, 30) == 0.0
        assert availability_at(25, 0, 20) == 1.0

    def test_no_adp_is_unknown_not_zero(self):
        assert availability_at(None, 5, 30) is None


class TestAssignTiers:
    def test_cuts_at_the_largest_gaps(self):
        points = [350.0, 348.0, 346.0, 300.0, 298.0, 250.0]
        tiers = _assign_tiers(points, draftable=6)
        assert tiers[0] == tiers[1] == tiers[2]
        assert tiers[3] == tiers[4]
        assert len({tiers[0], tiers[3], tiers[5]}) == 3

    def test_tier_count_is_capped(self):
        # A long, evenly-spaced list would otherwise produce a tier per player.
        points = [float(200 - i) for i in range(150)]
        # MAX_TIERS across the prefix, plus the one trailing depth tier.
        assert max(_assign_tiers(points, draftable=150)) <= MAX_TIERS + 1

    def test_dense_list_does_not_explode_into_tiers(self):
        # The WR case: 129 players ~1 point apart used to yield 41 tiers.
        points = [300.0 - i * 1.1 for i in range(129)]
        assert max(_assign_tiers(points, draftable=60)) <= MAX_TIERS + 1

    def test_short_list_does_not_break_at_every_gap(self):
        # Fewer players than the tier cap must not mean one tier each — only
        # gaps that are actually cliffs relative to the rest should cut.
        points = [350.0, 348.0, 346.0, 344.0, 342.0]
        assert len(set(_assign_tiers(points, draftable=5))) == 1

    def test_players_past_the_draftable_range_share_a_trailing_tier(self):
        points = [float(100 - i) for i in range(40)]
        tiers = _assign_tiers(points, draftable=10)
        assert len(set(tiers[10:])) == 1
        assert tiers[-1] > tiers[9]

    def test_bottom_of_list_gaps_do_not_distort_the_top(self):
        # QB case: huge gaps among undrafted backups previously inflated the
        # threshold and collapsed the startable QBs into one tier.
        top = [380.0, 324.0, 323.0, 318.0, 317.0, 314.0]
        tail = [200.0, 150.0, 90.0, 20.0]
        tiers = _assign_tiers(top + tail, draftable=6)
        assert tiers[0] != tiers[1]  # the 56-point cliff after QB1 is a break

    def test_edge_cases(self):
        assert _assign_tiers([], draftable=5) == []
        assert _assign_tiers([100.0], draftable=5) == [1]
        assert _assign_tiers([10.0, 10.0, 10.0], draftable=3) == [1, 1, 1]


class TestAdpImplied:
    CURVE = [(1.0, 350.0), (10.0, 300.0), (50.0, 200.0), (100.0, 120.0)]

    def test_interpolates_between_known_points(self):
        assert _adp_implied(self.CURVE, 30.0) == 250.0

    def test_clamps_outside_the_curve(self):
        assert _adp_implied(self.CURVE, 0.5) == 350.0
        assert _adp_implied(self.CURVE, 500.0) == 120.0

    def test_monotonic_along_the_curve(self):
        values = [_adp_implied(self.CURVE, a) for a in (5, 20, 40, 80)]
        assert values == sorted(values, reverse=True)

    def test_empty_curve_yields_nothing(self):
        assert _adp_implied([], 20.0) is None


class TestBlend:
    def test_rookie_with_no_history_uses_espn_alone(self):
        # The bug this whole feature exists to fix: no history must not mean
        # "not on the board".
        points, source = _blend(300.0, None, 0)
        assert points == 300.0
        assert source == "espn"

    def test_established_player_blends_both(self):
        points, source = _blend(300.0, 260.0, 12)
        assert source == "blend"
        assert 260.0 < points < 300.0

    def test_thin_sample_leans_harder_on_espn(self):
        thin, _ = _blend(300.0, 260.0, 5)
        established, _ = _blend(300.0, 260.0, 12)
        assert thin > established

    def test_history_only_when_espn_is_missing(self):
        assert _blend(None, 260.0, 12) == (260.0, "history")

    def test_thin_history_alone_is_not_trusted(self):
        assert _blend(None, 260.0, 1)[1] == "none"

    def test_nothing_known(self):
        assert _blend(None, None, 0) == (0.0, "none")


class TestStatusAdjust:
    def test_healthy_rostered_player_untouched(self):
        points, source, status = _status_adjust(
            220.0, "blend", espn=200.0, own_total=250.0,
            injury_status=None, team="SF",
        )
        assert (points, source, status) == (220.0, "blend", None)

    def test_injury_history_cannot_inflate_above_espn(self):
        # The Kittle case: history says 265, ESPN (injury-aware) says 177.
        points, source, status = _status_adjust(
            216.0, "blend", espn=177.0, own_total=265.0,
            injury_status="PUP", team="SF",
        )
        assert points == 177.0
        assert source == "espn_injury"
        assert status == "injured"

    def test_injury_with_no_espn_number_discounts_history(self):
        points, source, status = _status_adjust(
            250.0, "history", espn=None, own_total=250.0,
            injury_status="IR", team="BUF",
        )
        assert points < 250.0  # heavy IR haircut
        assert status == "injured"

    def test_injury_does_not_lift_when_history_is_already_lower(self):
        # If our number is already below ESPN, an injury flag shouldn't raise it.
        points, _, status = _status_adjust(
            150.0, "blend", espn=177.0, own_total=140.0,
            injury_status="doubtful", team="SF",
        )
        assert points == 150.0
        assert status == "injured"

    def test_teamless_player_drops_history_for_the_fill_pass(self):
        # The Diggs case: unsigned, so his stale history is discarded and he's
        # handed to the ADP-implied fill pass (source "none").
        points, source, status = _status_adjust(
            223.0, "history", espn=None, own_total=223.0,
            injury_status=None, team=None,
        )
        assert points == 0.0
        assert source == "none"
        assert status == "free_agent"

    def test_questionable_is_not_treated_as_serious(self):
        # Day-to-day tags shouldn't gut a projection.
        points, source, status = _status_adjust(
            220.0, "blend", espn=200.0, own_total=250.0,
            injury_status="Questionable", team="SF",
        )
        assert points == 220.0
        assert status is None


def _cand(pid, name, position, vor, adp, **extra):
    """A minimal board row shaped like compute_draft_board output."""
    return {
        "player_id": pid,
        "name": name,
        "position": position,
        "team": "AAA",
        "vor": vor,
        "proj_points": 200.0 + vor,
        "adp": adp,
        "adp_stdev": extra.get("adp_stdev", 5.0),
        "adp_delta": extra.get("adp_delta", 0),
        "value_score": extra.get("value_score", 0.0),
        "tier": extra.get("tier", 3),
        "is_tier_end": extra.get("is_tier_end", False),
        "overall_rank": extra.get("overall_rank", 50),
        "injury_status": extra.get("injury_status"),
        "bye_week": extra.get("bye_week", 10),
    }


# Emeka's league: 1 QB, 1 RB, 2 WR, 1 TE, 2 FLEX, 1 K, 1 DEF
FLEX_LEAGUE = ["QB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF", "BN", "BN"]


class TestRosterSlots:
    def test_separates_dedicated_from_flex(self):
        dedicated, flex, superflex = _roster_slots(FLEX_LEAGUE)
        assert dedicated == {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
        assert flex == 2
        assert superflex == 0

    def test_superflex_counted_separately(self):
        _, _, superflex = _roster_slots(
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]
        )
        assert superflex == 1


class TestLineupValue:
    def test_open_dedicated_slot_fills_a_starter(self):
        value, is_starter, _ = _lineup_value(
            "RB", vor=30.0, proj_points=250.0, held=Counter(),
            dedicated={"RB": 1}, flex_open=2, superflex_open=0,
        )
        assert is_starter is True
        assert value >= 30.0

    def test_needed_starter_is_floored_even_below_replacement(self):
        # No RB yet, only a below-replacement RB left — still worth starting.
        value, is_starter, _ = _lineup_value(
            "RB", vor=-20.0, proj_points=150.0, held=Counter(),
            dedicated={"RB": 1}, flex_open=0, superflex_open=0,
        )
        assert is_starter is True
        assert value > 0

    def test_backup_qb_is_heavily_discounted(self):
        # You already have your QB; a second barely plays.
        value, is_starter, _ = _lineup_value(
            "QB", vor=80.0, proj_points=380.0, held=Counter({"QB": 1}),
            dedicated={"QB": 1}, flex_open=2, superflex_open=0,
        )
        assert is_starter is False
        assert value < 10  # 80 * 0.10

    def test_rb_depth_outranks_a_backup_qb_and_te(self):
        # The exact bug: flex full, so RB is "bench" — but a startable RB must
        # still beat a 2nd QB and a 2nd TE that can't crack the lineup.
        held = Counter({"QB": 1, "RB": 2, "WR": 3, "TE": 1})
        rb, _, _ = _lineup_value(
            "RB", vor=-25.0, proj_points=210.0, held=held,
            dedicated={"QB": 1, "RB": 1, "WR": 2, "TE": 1}, flex_open=0, superflex_open=0,
        )
        qb, _, _ = _lineup_value(
            "QB", vor=90.0, proj_points=360.0, held=held,
            dedicated={"QB": 1, "RB": 1, "WR": 2, "TE": 1}, flex_open=0, superflex_open=0,
        )
        te, _, _ = _lineup_value(
            "TE", vor=45.0, proj_points=200.0, held=held,
            dedicated={"QB": 1, "RB": 1, "WR": 2, "TE": 1}, flex_open=0, superflex_open=0,
        )
        assert rb > qb
        assert rb > te

    def test_flex_slot_makes_a_second_rb_a_starter(self):
        value, is_starter, reason = _lineup_value(
            "RB", vor=20.0, proj_points=200.0, held=Counter({"RB": 1}),
            dedicated={"RB": 1}, flex_open=2, superflex_open=0,
        )
        assert is_starter is True
        assert "FLEX" in reason


class TestRecommendCap:
    def test_single_qb_league_caps_at_two(self):
        assert _recommend_cap("QB", starters=1.0) == 2

    def test_superflex_lifts_the_qb_cap(self):
        assert _recommend_cap("QB", starters=1.55) >= 3

    def test_kicker_capped_at_one(self):
        assert _recommend_cap("K", starters=1.0) == 1


class TestRecommendPicks:
    def _board(self):
        # A deep board: strong RBs and WRs, a couple of good TEs and QBs.
        board = []
        for i in range(12):
            board.append(_cand(f"rb{i}", f"RB {i}", "RB", vor=120 - i * 8, adp=i * 3 + 1))
            board.append(_cand(f"wr{i}", f"WR {i}", "WR", vor=118 - i * 8, adp=i * 3 + 2))
        for i in range(6):
            board.append(_cand(f"te{i}", f"TE {i}", "TE", vor=90 - i * 12, adp=i * 8 + 5))
            board.append(_cand(f"qb{i}", f"QB {i}", "QB", vor=80 - i * 10, adp=i * 8 + 9))
        return board

    def _late(self):
        return [
            _cand("k0", "Kicker 0", "K", vor=0, adp=150, overall_rank=None),
            _cand("d0", "Defense 0", "DEF", vor=0, adp=155, overall_rank=None),
        ]

    def test_does_not_stack_one_position(self):
        # Draft greedily from suggestions; the roster must not become all TEs.
        board = self._board()
        mine: list[str] = []
        for _ in range(10):
            recs = recommend_picks(board, STANDARD, mine, mine, limit=1)
            mine.append(recs[0]["player_id"])
        counts = Counter(pid[:2] for pid in mine)
        assert counts["te"] <= 3  # never a tight-end pile
        assert counts["rb"] >= 2 and counts["wr"] >= 2

    def test_kdef_hidden_early(self):
        # Round 1 with a full draft ahead — no kicker or defense suggested.
        recs = recommend_picks(
            self._board(), STANDARD, [], [], limit=6,
            late_round=self._late(), rounds=16,
        )
        assert all(r["position"] not in ("K", "DEF") for r in recs)

    def test_kdef_surface_when_forced(self):
        # 15 of 16 picks used, still no K/DEF — they must top the list now.
        board = self._board()
        mine = [f"rb{i}" for i in range(6)] + [f"wr{i}" for i in range(6)] + [
            "te0", "qb0", "rb6"
        ]
        recs = recommend_picks(
            board, STANDARD, mine, mine, limit=3,
            late_round=self._late(), rounds=16,
        )
        assert recs[0]["position"] in ("K", "DEF")

    def test_never_recommends_a_second_kicker(self):
        board = self._board()
        mine = ["k0"] + [f"rb{i}" for i in range(6)] + [f"wr{i}" for i in range(6)]
        recs = recommend_picks(
            board, STANDARD, mine, mine, limit=5,
            late_round=self._late(), rounds=16,
        )
        # DEF is still owed and should show; a 2nd kicker must not.
        assert all(r["position"] != "K" for r in recs)
