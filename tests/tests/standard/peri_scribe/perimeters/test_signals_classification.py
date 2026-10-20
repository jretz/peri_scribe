"""Classification evidence retains the measurements consumed by border policy."""

from __future__ import annotations

import dataclasses

import pytest
import shapely

import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.signals
import tests.helpers.factories.peri_scribe.perimeters.signals
from measurement_units import units


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        shapely.GeometryCollection(),
        shapely.Point(200.0, 0.0),
        shapely.Point(100.0, 0.0),
        shapely.box(90.0, 0.0, 110.0, 100.0),
        shapely.GeometryCollection([shapely.Point(200.0, 200.0)]),
        shapely.GeometryCollection([
            shapely.LineString([(101.0, 0.0), (101.0, 5.0)]),
            shapely.Point(102.0, 0.0),
        ]),
        shapely.GeometryCollection([
            shapely.box(120.0, 0.0, 140.0, 20.0),
            shapely.box(130.0, 0.0, 150.0, 20.0),
        ]),
        shapely.GeometryCollection([
            shapely.GeometryCollection([
                shapely.box(120.0, 0.0, 140.0, 20.0),
                shapely.Point(130.0, 30.0),
            ]),
            shapely.box(130.0, 0.0, 150.0, 20.0),
        ]),
        shapely.GeometryCollection([
            shapely.box(1.0, 1.0, 2.0, 2.0),
            shapely.Point(5.0, 5.0),
        ]),
        shapely.GeometryCollection([
            shapely.box(90.0, 0.0, 99.0, 10.0),
            shapely.box(101.0, 0.0, 110.0, 10.0),
        ]),
    ],
)
@pytest.mark.parametrize("inside_threshold", [0.0, 0.5, 1.0])
def test_classification_geometry_signal_preserves_full_evidence(
    geometry: shapely.Geometry | None,
    inside_threshold: float,
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> None:
    config = dataclasses.replace(
        tests.helpers.factories.peri_scribe.perimeters.signals.PLANAR_CONFIG,
        inside_area_fraction_threshold=inside_threshold,
    )
    full = peri_scribe.perimeters.signals.geometry_signal(
        geometry,
        boundaries,
        config,
    )
    evidence = peri_scribe.perimeters.signals.classification_geometry_signal(
        geometry,
        boundaries,
        config,
    )
    assert evidence.distance_to_boundary == full.distance_to_boundary
    assert evidence.outside_area_fraction == full.outside_area_fraction
    assert evidence.inside_area_fraction == full.inside_area_fraction
    assert evidence.crosses == full.crosses
    assert evidence.near == full.near
    assert evidence.inside == full.inside


def test_classification_geometry_signal_avoids_outside_union(
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry = shapely.GeometryCollection([
        shapely.box(120.0, 0.0, 140.0, 20.0),
        shapely.box(130.0, 0.0, 150.0, 20.0),
    ])
    monkeypatch.setattr(
        shapely,
        "union_all",
        lambda _parts: pytest.fail("outside-area union is unnecessary"),
    )
    evidence = peri_scribe.perimeters.signals.classification_geometry_signal(
        geometry,
        boundaries,
        tests.helpers.factories.peri_scribe.perimeters.signals.PLANAR_CONFIG,
    )
    assert evidence.outside_area_fraction == pytest.approx(1.0)
    assert not evidence.crosses
    assert not isinstance(
        evidence,
        peri_scribe.perimeters.classification_data.GeometrySignal,
    )


@pytest.mark.parametrize(("buffer_meters", "near"), [(0.999, False), (1.0, True)])
def test_classification_geometry_signal_preserves_near_boundary(
    buffer_meters: float,
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    *,
    near: bool,
) -> None:
    config = dataclasses.replace(
        tests.helpers.factories.peri_scribe.perimeters.signals.PLANAR_CONFIG,
        near_border_buffer=buffer_meters * units.meters,
    )
    evidence = peri_scribe.perimeters.signals.classification_geometry_signal(
        shapely.GeometryCollection([shapely.box(101.0, 0.0, 102.0, 10.0)]),
        boundaries,
        config,
    )
    assert evidence.near is near
