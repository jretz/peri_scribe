"""Ranked output views obey the executable identity and temporal policies."""

import pathlib

import tests.formal.helpers.ranked_views


def test_top_fires_matches_ranked_identity_model() -> None:
    assert (
        len(tests.formal.helpers.ranked_views.rankings())
        == tests.formal.helpers.ranked_views.RANKING_COUNT
    )
    tests.formal.helpers.ranked_views.check_rankings()


def test_top_fires_filters_excluded_scores_before_limit() -> None:
    tests.formal.helpers.ranked_views.check_exclusion_before_limit()


def test_fire_growth_matches_selected_past_evidence_model() -> None:
    assert (
        len(tests.formal.helpers.ranked_views.growth_histories())
        == tests.formal.helpers.ranked_views.GROWTH_COUNT
    )
    tests.formal.helpers.ranked_views.check_growth()


def test_recent_views_match_inclusive_window_model() -> None:
    tests.formal.helpers.ranked_views.check_windows()


def test_ranked_scores_and_description_notes_preserve_associated_source(
    tmp_path: pathlib.Path,
) -> None:
    tests.formal.helpers.ranked_views.check_associated_outputs(tmp_path)
