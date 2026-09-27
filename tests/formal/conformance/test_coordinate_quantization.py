"""The proved grid rounding agrees with actual scalar, vector, and database queries."""

import itertools
import pathlib

import numpy as np
import shapely

import spatial_data.point_store
import tests.formal.helpers.coordinate_quantization
import tests.formal.helpers.oracle
import tests.formal.helpers.spatial_index


def test_quantize_centroids_matches_signed_rational_ties_to_even() -> None:
    longitude = tests.formal.helpers.coordinate_quantization.axis_values(180)
    latitude = tests.formal.helpers.coordinate_quantization.axis_values(90)
    coordinates = np.array(
        list(itertools.zip_longest(longitude, latitude, fillvalue=0.0)),
    )
    commands = [
        tests.formal.helpers.coordinate_quantization.command(float(value))
        for value in coordinates.flat
    ]
    expected = np.array(
        tests.formal.helpers.oracle.evaluate(commands, executable="oracleSpatial"),
        dtype="<i4",
    ).reshape(coordinates.shape)
    actual = spatial_data.point_store.quantize_centroids(coordinates)
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == np.dtype("<i4")
    longitude_limit = tests.formal.helpers.spatial_index.LONGITUDE_LIMIT
    latitude_limit = tests.formal.helpers.spatial_index.LATITUDE_LIMIT
    for pair, encoded in zip(coordinates, expected, strict=True):
        assert spatial_data.point_store.encode_longitude(float(pair[0])) == encoded[0]
        assert spatial_data.point_store.encode_latitude(float(pair[1])) == encoded[1]
        assert -longitude_limit <= encoded[0] <= longitude_limit
        assert -latitude_limit <= encoded[1] <= latitude_limit


def test_point_counts_within_keeps_decoded_points_at_float_envelope_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    points, boxes = tests.formal.helpers.coordinate_quantization.query_cases()
    commands = [
        tests.formal.helpers.coordinate_quantization.command(value)
        for box in boxes
        for value in box
    ]
    expected_bounds = iter(
        tests.formal.helpers.oracle.evaluate(commands, executable="oracleSpatial"),
    )
    encoded_points = np.array(points, dtype="<i4")
    decoded = encoded_points / spatial_data.point_store.COORDINATE_SCALE
    geometries = list(itertools.starmap(shapely.box, boxes))
    expected_counts = []
    for box, geometry in zip(boxes, geometries, strict=True):
        expected = (
            next(expected_bounds)[0],
            next(expected_bounds)[0],
            next(expected_bounds)[0],
            next(expected_bounds)[0],
        )
        assert spatial_data.point_store.encoded_box(box) == expected
        inside = (
            (box[0] <= decoded[:, 0])
            & (decoded[:, 0] <= box[2])
            & (box[1] <= decoded[:, 1])
            & (decoded[:, 1] <= box[3])
        )
        retained = spatial_data.point_store.points_within_box(encoded_points, expected)
        assert {tuple(point) for point in encoded_points[inside]} <= {
            tuple(point) for point in retained
        }
        expected_counts.append(
            int(
                np.count_nonzero(
                    shapely.contains_xy(geometry, decoded[:, 0], decoded[:, 1]),
                ),
            ),
        )
    path = tmp_path / "quantized.sqlite"
    tests.formal.helpers.spatial_index.database(path, points)
    assert (
        spatial_data.point_store.point_counts_within(geometries, path)
        == expected_counts
    )
