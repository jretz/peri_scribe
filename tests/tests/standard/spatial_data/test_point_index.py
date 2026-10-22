import collections

import numpy as np
import pytest

import spatial_data.point_index


def test_longitude_index_build_owns_unchanging_coordinates() -> None:
    points = np.array([[3, -1], [-2, 4], [3, -1], [0, 0]], dtype="<i4")
    index = spatial_data.point_index.LongitudeIndex.build(points)
    points[:] = 99
    assert index.points.tolist() == [[-2, 4], [0, 0], [3, -1], [3, -1]]
    assert index.longitudes.tolist() == [-2, 0, 3, 3]
    assert not index.points.flags.writeable
    assert not index.longitudes.flags.writeable


def test_longitude_index_build_preserves_read_only_input() -> None:
    points = np.array([[1, 0], [-1, 0]], dtype="<i4")
    points.flags.writeable = False
    spatial_data.point_index.LongitudeIndex.build(points)
    assert points.tolist() == [[1, 0], [-1, 0]]


def test_longitude_index_select_keeps_duplicate_envelope_endpoints() -> None:
    points = np.array(
        [[1, 1], [-1, 0], [1, 1], [-1, 0], [0, 0], [0, -1], [0, 2], [2, 0]],
        dtype="<i4",
    )
    index = spatial_data.point_index.LongitudeIndex.build(points)
    selected = index.select((-1, 0, 1, 1))
    assert collections.Counter(map(tuple, selected.tolist())) == collections.Counter([
        (-1, 0),
        (-1, 0),
        (0, 0),
        (1, 1),
        (1, 1),
    ])


@pytest.mark.parametrize(
    "box",
    [(3, 0, 4, 1), (-4, 0, -3, 1), (1, 0, -1, 1), (-1, 2, 1, -2)],
)
def test_longitude_index_select_returns_empty_for_excluded_or_reversed_bounds(
    box: tuple[int, int, int, int],
) -> None:
    index = spatial_data.point_index.LongitudeIndex.build(
        np.array([[-1, 0], [0, 0], [1, 1]], dtype="<i4"),
    )
    assert index.select(box).shape == (0, 2)


def test_longitude_index_select_handles_empty_tile() -> None:
    index = spatial_data.point_index.LongitudeIndex.build(np.empty((0, 2), dtype="<i4"))
    assert index.select((-1, -1, 1, 1)).shape == (0, 2)


def test_longitude_index_select_handles_signed_int32_extremes() -> None:
    low, high = int(np.iinfo(np.int32).min), int(np.iinfo(np.int32).max)
    points = np.array([[high, high], [low, low]], dtype="<i4")
    index = spatial_data.point_index.LongitudeIndex.build(points)
    assert index.select((low, low, high, high)).tolist() == [[low, low], [high, high]]


def test_longitude_index_select_cannot_mutate_the_index_through_a_result() -> None:
    index = spatial_data.point_index.LongitudeIndex.build(
        np.array([[0, 0], [1, 1]], dtype="<i4"),
    )
    selected = index.select((0, 0, 1, 1))
    selected[:] = 8
    assert index.select((0, 0, 1, 1)).tolist() == [[0, 0], [1, 1]]
