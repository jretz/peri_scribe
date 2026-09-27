"""Keep anonymous score ownership intact through serialized score documents."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.fires.scores
import peri_scribe.models
import tests.helpers.doubles.peri_scribe.fires.scores
import tests.helpers.factories.peri_scribe.fires.scores


def test_score_fires_persists_components_without_reinterpreting_identifiers(
    tmp_path: pathlib.Path,
    score_fires_stubs: typing.Callable[
        ...,
        tests.helpers.doubles.peri_scribe.fires.scores.ScoreFiresStubs,
    ],
) -> None:
    points = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        (None, "Canyon", 100),
        (None, "Canyon", 200),
        ("component:alaska", "Canyon", 300),
        ("id:component:alaska", "Canyon", 400),
    ]).assign(
        fire_component_id=["alaska", "california", "external", "escaped"],
        source_attributes="{}",
    )
    captured = score_fires_stubs(points=points)

    peri_scribe.fires.scores.score_fires(tmp_path)

    document = peri_scribe.models.FireScores.model_validate_json(
        captured.writes[0][1].model_dump_json(),
    )
    assert {
        (entry.identifier, entry.component_id): entry.area for entry in document.fires
    } == {
        (None, "alaska"): 100,
        (None, "california"): 200,
        ("component:alaska", None): 300,
        ("id:component:alaska", None): 400,
    }
