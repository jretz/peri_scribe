"""Only selected report fires need location measurements and report details."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import shapely.geometry

import peri_scribe.models
import peri_scribe.presentation.views
import peri_scribe.report.gathering
import peri_scribe.report.locations
import tests.helpers.doubles.peri_scribe.report.gathering
import tests.helpers.factories.peri_scribe.presentation.views


if typing.TYPE_CHECKING:
    import pytest


def test_report_from_fires_locates_only_selected_fires(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fires = [
        dataclasses.replace(
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                f"Fire {index}",
                identifiers=frozenset({str(index)}),
            ),
            status=peri_scribe.models.FireStatus.INACTIVE,
            point=shapely.geometry.Point(-120, 35 + index / 100),
        )
        for index in range(peri_scribe.presentation.views.TOP_FIRE_COUNT + 1)
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
    measured: list[shapely.Geometry] = []
    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        tests.helpers.doubles.peri_scribe.report.gathering.make_city_measurement_recorder(
            measured=measured,
        ),
    )

    report = peri_scribe.report.gathering.report_from_fires(fires, scores, tmp_path)

    assert len(measured) == len(report.fire_details)
    assert set(measured) == {fire.point for fire in fires[1:]}


def test_report_from_fires_locates_namesakes_once_across_overlapping_sections(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fires = [
        dataclasses.replace(
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                "Same name",
                identifiers=frozenset({identifier}),
            ),
            type_one=True,
            point=shapely.geometry.Point(-120, 35 + index),
        )
        for index, identifier in enumerate(("first", "second"))
    ]
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                fire.name,
                identifier,
                score,
                "",
            )
            for fire, identifier, score in zip(
                fires,
                ("first", "second"),
                (1, 2),
                strict=True,
            )
        ],
    )
    measured: list[shapely.Geometry] = []
    monkeypatch.setattr(
        peri_scribe.report.locations,
        "nearest_city",
        tests.helpers.doubles.peri_scribe.report.gathering.make_city_measurement_recorder(
            measured=measured,
        ),
    )

    report = peri_scribe.report.gathering.report_from_fires(fires, scores, tmp_path)

    assert len(measured) == len(fires)
    assert {entry.identifier for entry in report.fire_details} == {"first", "second"}
    assert report.type_one_fires == tuple(reversed(report.top_fires))
    assert all(entry.location for entry in report.fire_details)


def test_report_from_fires_preserves_excluded_namesakes_score_ownership(
    tmp_path: pathlib.Path,
) -> None:
    ranked = [
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            f"Ranked {index}",
            identifiers=frozenset({str(index)}),
        )
        for index in range(peri_scribe.presentation.views.TOP_FIRE_COUNT)
    ]
    selected = dataclasses.replace(
        tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "Namesake",
            identifiers=frozenset({"selected"}),
        ),
        type_one=True,
    )
    excluded = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Namesake",
        identifiers=frozenset({"excluded"}),
    )
    scores = peri_scribe.models.FireScores(
        version="regression",
        fires=[
            *(
                tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                    fire.name,
                    str(index),
                    index + 2,
                    "",
                )
                for index, fire in enumerate(ranked)
            ),
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                "Namesake",
                None,
                1,
                "Owned by the final namesake in the complete collection",
            ),
        ],
    )

    report = peri_scribe.report.gathering.report_from_fires(
        [*ranked, selected, excluded],
        scores,
        tmp_path,
    )

    assert report.type_one_fires[0].score is None
    assert all(entry.identifier != "excluded" for entry in report.fire_details)
