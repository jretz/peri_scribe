"""Bounded raw evidence produces the existing exact ordered history rows."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import shapely

import peri_scribe.fires.bounded_sources
import peri_scribe.fires.history
import peri_scribe.fires.incident_history
import peri_scribe.geo.catalog
import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.geo.catalog


if typing.TYPE_CHECKING:
    import pytest


def test_build_rows_matches_complete_history_and_incident_policy(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    monkeypatch.setattr(
        peri_scribe.fires.bounded_sources,
        "load_boundaries",
        lambda _: None,
    )
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        groups = peri_scribe.fires.bounded_sources.prepare_groups(catalog)
        keys = {id(fire): f"key-{index}" for index, fire in enumerate(groups.fires)}
        read = catalog.hydrate(tuple(range(len(catalog.entries))))
        expected_perimeters, expected_points = (
            peri_scribe.fires.history.history_layer_rows(
                groups,
                {},
                list(read.rows),
                list(read.paths),
                tmp_path,
                derivation_keys=keys,
            )
        )
        expected_incidents = peri_scribe.fires.incident_history.incident_layer_rows(
            read,
            groups,
            tmp_path,
            derivation_keys=keys,
        )
        actual, classifications = peri_scribe.fires.bounded_sources.build_rows(
            catalog,
            groups,
            keys,
            tmp_path,
            cached={},
            classifications={},
        )
    assert actual == peri_scribe.fires.bounded_sources.Rows(
        perimeters=expected_perimeters,
        points=expected_points,
        incidents=expected_incidents,
    )
    assert classifications == {}


def test_build_fire_omits_complex_parent_after_exact_source_diagnostics(
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        groups = peri_scribe.fires.bounded_sources.prepare_groups(catalog)
        groups = dataclasses.replace(groups, complex_identifiers=frozenset({"fire-0"}))
        result = peri_scribe.fires.bounded_sources.build_fire(
            0,
            catalog=catalog,
            groups=groups,
            keys={},
            cached={},
            classifications={},
            boundaries=None,
        )
    assert result.rows == peri_scribe.fires.bounded_sources.Rows(
        perimeters=[],
        points=[],
        incidents=[],
    )
    assert result.classification is None


def test_build_fire_retains_authenticated_cached_rows(tmp_path: pathlib.Path) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    expected = peri_scribe.fires.bounded_sources.Rows(
        perimeters=[{"complete": "perimeter"}],
        points=[],
        incidents=[],
    )
    classification = peri_scribe.models.FireClassification(
        classification=peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
        outside_area_fraction=0.0,
        inside_area_fraction=1.0,
    )
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        groups = peri_scribe.fires.bounded_sources.prepare_groups(catalog)
        fire = groups.fires[0]
        result = peri_scribe.fires.bounded_sources.build_fire(
            0,
            catalog=catalog,
            groups=groups,
            keys={},
            cached={id(fire): expected},
            classifications={id(fire): classification},
            boundaries=None,
        )
    assert result.rows is expected
    assert result.classification is classification


def test_build_rows_calculates_missing_classifications(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.factories.peri_scribe.geo.catalog.create(tmp_path)
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.box(-1, -1, 1, 1),
        border=shapely.LineString([(1, -1), (1, 1)]),
    )
    monkeypatch.setattr(
        peri_scribe.fires.bounded_sources,
        "load_boundaries",
        lambda _: boundaries,
    )
    with peri_scribe.geo.catalog.open_catalog(tmp_path) as catalog:
        groups = peri_scribe.fires.bounded_sources.prepare_groups(catalog)
        keys = {id(fire): "key" for fire in groups.fires}
        _rows, classifications = peri_scribe.fires.bounded_sources.build_rows(
            catalog,
            groups,
            keys,
            tmp_path,
            cached={},
            classifications={},
        )
    assert set(classifications) == set(keys)


def test_load_boundaries_retains_existing_missing_input_behavior(
    tmp_path: pathlib.Path,
) -> None:
    assert peri_scribe.fires.bounded_sources.load_boundaries(tmp_path) is None


def test_load_boundaries_returns_complete_input(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundaries = peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.box(-1, -1, 1, 1),
        border=shapely.LineString([(1, -1), (1, 1)]),
    )
    monkeypatch.setattr(
        peri_scribe.perimeters.border_classification,
        "load_boundaries",
        lambda _: boundaries,
    )
    assert peri_scribe.fires.bounded_sources.load_boundaries(tmp_path) is boundaries
