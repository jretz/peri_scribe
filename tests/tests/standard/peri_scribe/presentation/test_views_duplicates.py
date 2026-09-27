"""Ranked fire identities remain unique when several score aliases resolve to one."""

import peri_scribe.models
import peri_scribe.presentation.views
import tests.helpers.factories.peri_scribe.presentation.views


def test_top_fires_deduplicates_alias_matches_before_applying_limit() -> None:
    first = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "First",
        identifiers=frozenset({"first", "alias"}),
    )
    second = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Second",
        identifiers=frozenset({"second"}),
    )
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "First",
                "first" if index % 2 else "alias",
                100,
                "",
            )
            for index in range(peri_scribe.presentation.views.TOP_FIRE_COUNT)
        ]
        + [
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Second",
                "second",
                1,
                "",
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([first, second], scores) == [
        first,
        second,
    ]
