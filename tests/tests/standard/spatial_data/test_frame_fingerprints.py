"""Ordered evidence keys must change whenever a consumed source value changes."""

from __future__ import annotations

import datetime
import hashlib
import struct

import geopandas
import numpy as np
import pandas as pd
import pytest
import shapely

import spatial_data.cache_values
import spatial_data.frame_fingerprints
import tests.helpers.factories.peri_scribe.fires.scores
from measurement_units import units


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


@pytest.mark.parametrize("index", [[], [9, 9]])
def test_frame_rows_accepts_zero_columns_without_an_active_geometry(
    index: list[int],
) -> None:
    assert (
        spatial_data.frame_fingerprints.frame_rows(
            geopandas.GeoDataFrame(index=index),
        ).rows
        == ()
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NA,
        pd.NaT,
        True,
        10**40,
        np.int64(1),
        np.float32(1.25),
        -0.0,
        float("inf"),
        struct.unpack("!d", bytes.fromhex("7ff8000000000007"))[0],
        "Unicode 🔥",
        b"\x00\xff",
        pd.Timestamp("2026-01-01T00:00:00.123456789Z"),
        pd.Timestamp("2026-01-01").as_unit("s"),
        datetime.datetime(2026, 1, 1, fold=1),
        pd.Timedelta(1, unit="ns"),
        datetime.timedelta(microseconds=1),
        12.5 * units.acres,
        {"second": np.int32(2), "first": (None, -0.0)},
        frozenset({"a", "b"}),
        shapely.set_srid(shapely.Point(1, 2), 4326),
        shapely.Point(),
    ],
)
def test_frame_rows_preserves_exact_object_scalar_payloads(value: object) -> None:
    frame = geopandas.GeoDataFrame({"value": pd.Series([value], dtype=object)})
    expected = hashlib.sha256(spatial_data.cache_values.dumps((value,))).digest()
    assert spatial_data.frame_fingerprints.frame_rows(frame).rows == (expected,)


@pytest.mark.parametrize(
    ("dtype", "values", "expected"),
    [
        ("int64", [1, 2], (1, 2)),
        ("float32", [1.25, -0.0], (1.25, -0.0)),
        ("Int64", [1, None], (np.int64(1), pd.NA)),
        ("Float32", [1.25, None], (np.float32(1.25), pd.NA)),
        ("boolean", [True, None], (np.bool_(1), pd.NA)),
        ("string", ["a", None], ("a", pd.NA)),
        (
            "datetime64[ns, UTC]",
            ["2026-01-01T00:00:00.123456789Z", None],
            (pd.Timestamp("2026-01-01T00:00:00.123456789Z"), pd.NaT),
        ),
        ("timedelta64[ns]", [1, None], (pd.Timedelta(1, unit="ns"), pd.NaT)),
    ],
)
def test_frame_rows_preserves_dtype_specific_scalar_boxing(
    dtype: str,
    values: list[object],
    expected: tuple[object, ...],
) -> None:
    frame = geopandas.GeoDataFrame({"value": pd.Series(values, dtype=dtype)})
    assert spatial_data.frame_fingerprints.frame_rows(frame).rows == tuple(
        hashlib.sha256(spatial_data.cache_values.dumps((value,))).digest()
        for value in expected
    )


def test_frame_rows_retains_duplicate_columns_in_positional_order() -> None:
    rows = [(1, "one"), (2, "two")]
    frame = geopandas.GeoDataFrame(pd.DataFrame(rows, columns=["same", "same"]))
    assert spatial_data.frame_fingerprints.frame_rows(frame).rows == tuple(
        hashlib.sha256(spatial_data.cache_values.dumps(row)).digest() for row in rows
    )


def test_frame_rows_preserves_missing_empty_and_srid_geometry() -> None:
    geometries = [None, shapely.Point(), shapely.set_srid(shapely.Point(1, 2), 4326)]
    frame = geopandas.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
    assert spatial_data.frame_fingerprints.frame_rows(frame).rows == tuple(
        hashlib.sha256(spatial_data.cache_values.dumps((geometry,))).digest()
        for geometry in geometries
    )


def test_frame_rows_retains_schema_when_no_rows_are_selected() -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
    ])
    empty_fingerprints = spatial_data.frame_fingerprints.frame_rows(frame.iloc[:0])
    assert empty_fingerprints == spatial_data.frame_fingerprints.FrameRows(
        schema=spatial_data.frame_fingerprints.frame_rows(frame).schema,
        rows=(),
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
