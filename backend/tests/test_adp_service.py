from app.services.adp_service import (
    FFC_POSITION_ALIAS,
    FFC_WEIGHT,
    _consensus,
    _season_totals,
)


def _stat(source, split, season, total, period=0):
    return {
        "statSourceId": source,
        "statSplitTypeId": split,
        "seasonId": season,
        "scoringPeriodId": period,
        "appliedTotal": total,
    }


class TestSeasonTotals:
    def test_picks_the_season_total_not_a_weekly_row(self):
        stats = [
            _stat(1, 1, 2026, 22.0, period=13),  # weekly projection
            _stat(1, 0, 2026, 365.5),  # season projection
            _stat(0, 0, 2025, 366.9),  # last season actual
        ]
        assert _season_totals(stats, 2026) == (365.5, 366.9)

    def test_ignores_other_seasons(self):
        stats = [_stat(1, 0, 2024, 300.0), _stat(1, 0, 2026, 365.5)]
        projected, _ = _season_totals(stats, 2026)
        assert projected == 365.5

    def test_projection_and_actual_are_kept_apart(self):
        # statSourceId 1 is a projection, 0 is what actually happened.
        stats = [_stat(0, 0, 2026, 0.0), _stat(1, 0, 2026, 365.5)]
        projected, _ = _season_totals(stats, 2026)
        assert projected == 365.5

    def test_missing_and_empty_inputs(self):
        assert _season_totals([], 2026) == (None, None)
        assert _season_totals(None, 2026) == (None, None)
        assert _season_totals([_stat(1, 0, 2026, None)], 2026) == (None, None)


class TestConsensus:
    def test_blend_leans_toward_the_real_mock_draft_source(self):
        blended = _consensus(10.0, 20.0)
        assert blended == round(FFC_WEIGHT * 20.0 + (1 - FFC_WEIGHT) * 10.0, 2)
        assert blended > 15.0  # FFC carries more weight

    def test_falls_back_to_whichever_source_exists(self):
        assert _consensus(12.0, None) == 12.0
        assert _consensus(None, 8.0) == 8.0

    def test_no_sources_is_none(self):
        assert _consensus(None, None) is None

    def test_agreement_is_preserved(self):
        assert _consensus(5.0, 5.0) == 5.0


class TestPositionAliases:
    def test_kickers_are_normalised_to_our_label(self):
        # FFC calls them PK; everything else in the app says K. Getting this
        # wrong silently drops every kicker from the position match.
        assert FFC_POSITION_ALIAS["PK"] == "K"

    def test_defense_variants_normalise(self):
        assert FFC_POSITION_ALIAS["DST"] == "DEF"
        assert FFC_POSITION_ALIAS["D/ST"] == "DEF"
