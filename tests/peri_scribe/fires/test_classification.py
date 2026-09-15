"""Tests for peri_scribe.fires.classification."""

from __future__ import annotations

import pathlib
import typing

import shapely.geometry
import structlog

import peri_scribe.fires.classification
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import tests.factories
import tests.peri_scribe.fires.classification_helpers
from tests.factories import ACTIVE


if typing.TYPE_CHECKING:
    import pytest


def test_classify_fire_sources_returns_empty_without_non_complex_fires() -> None:
    fire = peri_scribe.models.Fire(
        name="Park Fire",
        status=ACTIVE,
        identifier="parent",
        aliases=frozenset({"parent"}),
    )
    groups = tests.peri_scribe.fires.classification_helpers.record_groups(
        fire=fire,
        complex_identifiers=frozenset({"parent"}),
    )
    assert (
        peri_scribe.fires.classification.classify_fire_sources(
            groups,
            pathlib.Path("/base"),
        )
        == {}
    )


def test_classify_fire_sources_returns_empty_when_boundaries_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)

    fail = tests.factories.raising_stub(FileNotFoundError("missing"))

    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        fail,
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.fires.classification.classify_fire_sources(
            tests.peri_scribe.fires.classification_helpers.record_groups(fire=fire),
            pathlib.Path("/base"),
        )
    assert result == {}
    assert [event["event"] for event in captured] == ["Skipping border classification"]


def test_classify_fire_sources_classifies_each_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = peri_scribe.models.Fire(name="Park Fire", status=ACTIVE)
    boundary = peri_scribe.perimeters.border_classification.Boundaries(
        box=shapely.geometry.box(0.0, 0.0, 10.0, 10.0),
        border=shapely.geometry.LineString([(10.0, 0.0), (10.0, 10.0)]),
    )
    classification = peri_scribe.models.FireClassification(
        classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        outside_area_fraction=0.0,
        inside_area_fraction=1.0,
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        lambda _base_dir: boundary,
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "classify_fire",
        lambda **_keywords: classification,
    )
    result = peri_scribe.fires.classification.classify_fire_sources(
        tests.peri_scribe.fires.classification_helpers.record_groups(fire=fire),
        pathlib.Path("/base"),
    )
    assert result == {id(fire): classification}
