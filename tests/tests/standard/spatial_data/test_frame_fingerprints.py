"""Ordered evidence keys must change whenever a consumed source value changes."""

from __future__ import annotations

import geopandas
import pytest

import spatial_data.frame_fingerprints
import tests.helpers.factories.peri_scribe.fires.scores


@pytest.mark.parametrize("change", ["value", "order", "schema", "crs", "geometry"])
def test_frame_rows_invalidates_changed_ordered_evidence(change: str) -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
        ("example", "Example", 200),
    ])
    changed = frame.copy()
    match change:
        case "value":
            changed.loc[0, "incident_size"] = 101
        case "order":
            changed = changed.iloc[::-1]
        case "schema":
            changed["incident_size"] = changed["incident_size"].astype("float64")
        case "crs":
            changed = changed.set_crs("EPSG:3857", allow_override=True)
        case _:
            changed.geometry = changed.geometry.translate(1)
    assert spatial_data.frame_fingerprints.frame_rows(frame) != (
        spatial_data.frame_fingerprints.frame_rows(changed)
    )


def test_frame_rows_ignores_labels_when_evidence_order_is_unchanged() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
        ("example", "Example", 200),
    ])
    changed = frame.copy()
    changed.index = [9, 9]
    assert spatial_data.frame_fingerprints.frame_rows(frame) == (
        spatial_data.frame_fingerprints.frame_rows(changed)
    )


def test_frame_rows_accepts_empty_frames_without_an_active_geometry() -> None:
    assert (
        spatial_data.frame_fingerprints.frame_rows(geopandas.GeoDataFrame()).rows == ()
    )


def test_selected_key_includes_identity_and_selected_order() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
        ("example", "Example", 200),
    ])
    fingerprints = (spatial_data.frame_fingerprints.frame_rows(frame),)
    keys = {
        spatial_data.frame_fingerprints.selected_key(fingerprints, positions, identity)
        for positions, identity in (
            (((0, 1),), "first"),
            (((1, 0),), "first"),
            (((0, 1),), "second"),
        )
    }
    expected_count = 3
    assert len(keys) == expected_count
