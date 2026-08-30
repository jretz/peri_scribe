"""Tests for peri_scribe.fires.classification."""

from __future__ import annotations

import pathlib
import typing

import shapely.geometry
import structlog

import peri_scribe.fires.classification
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.perimeters.border_classification
from tests.factories import ACTIVE, fire_record


if typing.TYPE_CHECKING:
    import pytest


def record_groups(
    *,
    fire: peri_scribe.models.Fire,
    complex_identifiers: frozenset[str] = frozenset(),
) -> peri_scribe.fires.sources.FireRecordGroups:
    identifiers = frozenset({fire.identifier}) if fire.identifier else frozenset()
    record = fire_record(
        "Park Fire",
        ACTIVE,
        identifiers=identifiers,
        geometry=shapely.geometry.Point(-120.0, 39.0),
    )
    path = pathlib.Path(
        "sources/CA_Perimeters_NIFC_FIRIS_public_view_0/000___/000000,lastEdit=0.gpkg",
    )
    return peri_scribe.fires.sources.FireRecordGroups(
        records=(record,),
        record_paths=(path,),
        fires=(fire,),
        groups=((0,),),
        complex_identifiers=complex_identifiers,
    )


def test_classify_fire_sources_returns_empty_without_non_complex_fires() -> None:
    fire = peri_scribe.models.Fire(
        name="Park Fire",
        status=ACTIVE,
        identifier="parent",
        aliases=frozenset({"parent"}),
    )
    groups = record_groups(
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

    def fail(_base_dir: pathlib.Path) -> object:
        message = "missing"
        raise FileNotFoundError(message)

    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        fail,
    )
    with structlog.testing.capture_logs() as captured:
        result = peri_scribe.fires.classification.classify_fire_sources(
            record_groups(fire=fire),
            pathlib.Path("/base"),
        )
    assert result == {}
    assert [event["event"] for event in captured] == [
        "Skipping border classification",
    ]


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
        distance_to_boundary_in_meters=1.0,
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
        record_groups(fire=fire),
        pathlib.Path("/base"),
    )
    assert result == {id(fire): classification}
