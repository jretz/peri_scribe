"""Holding fires retain score ownership without occupying a Top Fires place."""

from __future__ import annotations

import dataclasses
import typing

import peri_scribe.models
import peri_scribe.presentation.views
import tests.helpers.factories.peri_scribe.presentation.views


if typing.TYPE_CHECKING:
    import pytest


def test_top_fires_excludes_holding_before_applying_limit() -> None:
    holding = dataclasses.replace(
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "Holding",
            identifiers=frozenset({"holding"}),
        ),
        status=peri_scribe.models.FireStatus.HOLDING,
    )
    eligible = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Fire {index}",
            identifiers=frozenset({str(index)}),
        )
        for index in range(peri_scribe.presentation.views.TOP_FIRE_COUNT)
    ]
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Holding",
                "holding",
                1_000,
                "",
            ),
            *(
                tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                    fire.name,
                    str(index),
                    500 - index,
                    "",
                )
                for index, fire in enumerate(eligible)
            ),
        ],
    )
    assert peri_scribe.presentation.views.top_fires([holding, *eligible], scores) == (
        eligible
    )


def test_top_fires_keeps_holding_identifier_score_from_same_name_active_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holding = dataclasses.replace(
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "Timber",
            identifiers=frozenset({"holding"}),
        ),
        status=peri_scribe.models.FireStatus.HOLDING,
    )
    same_name = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Timber",
        identifiers=frozenset({"active"}),
    )
    other = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Other",
        identifiers=frozenset({"other"}),
    )
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                name,
                identifier,
                score,
                "",
            )
            for name, identifier, score in (
                ("Timber", "holding", 100),
                ("Other", "other", 50),
                ("Timber", "active", 1),
            )
        ],
    )
    monkeypatch.setattr(peri_scribe.presentation.views, "TOP_FIRE_COUNT", 1)
    assert peri_scribe.presentation.views.top_fires(
        [holding, same_name, other],
        scores,
    ) == [other]


def test_notable_score_threshold_counts_holding_in_agency_active_population() -> None:
    fires = [
        dataclasses.replace(
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                f"Fire {index}",
                identifiers=frozenset({str(index)}),
            ),
            status=(
                peri_scribe.models.FireStatus.HOLDING
                if index == 0
                else peri_scribe.models.FireStatus.ACTIVE
            ),
        )
        for index in range(6)
    ]
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                fire.name,
                str(index),
                index,
                "",
            )
            for index, fire in enumerate(fires)
        ],
    )

    expected_threshold = 4
    assert (
        peri_scribe.presentation.views.notable_score_threshold(fires, scores)
        == expected_threshold
    )


def test_type_one_fires_includes_holding_type_one_incident() -> None:
    holding = dataclasses.replace(
        tests.helpers.factories.peri_scribe.presentation.views.type_one_fire("Timber"),
        status=peri_scribe.models.FireStatus.HOLDING,
    )

    assert peri_scribe.presentation.views.type_one_fires([holding]) == [holding]
