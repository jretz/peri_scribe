"""A ranked report's displayed score retains the row that ranked its fire."""

import pathlib

import peri_scribe.models
import peri_scribe.report.gathering
import tests.helpers.factories.peri_scribe.presentation.views


def test_report_from_fires_preserves_highest_alias_score(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Alias",
        identifiers=frozenset({"a", "z"}),
    )
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Alias",
                "a",
                1,
                "Low",
            ),
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Alias",
                "z",
                100,
                "High",
            ),
        ],
    )
    report = peri_scribe.report.gathering.report_from_fires([fire], scores, tmp_path)
    assert report.top_fires[0].score == scores.fires[1].score
