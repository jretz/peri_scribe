"""Check proportions, per-fire orientation, holes, outlines, and north darts."""

import math

import numpy as np
import pytest
import shapely

import peri_scribe.presentation.preview_geometry


OPAQUE = 255
NEAR_WHITE = 240
MAXIMUM_COLOR_DISTANCE = 80


@pytest.mark.parametrize("angle", [0, 0.37, math.pi / 2, math.pi * 0.98])
def test_rotate_preserves_distances_and_points_north(angle: float) -> None:
    points = np.array(((0, 0), (1, 0), (0, 1)), dtype=float)
    result = peri_scribe.presentation.preview_geometry.rotate(points, angle)
    assert np.linalg.norm(result[1] - result[2]) == pytest.approx(math.sqrt(2))
    assert result[2] == pytest.approx((-math.sin(angle), -math.cos(angle)))


@pytest.mark.parametrize("tilt", [-0.8, 0.8, math.pi / 2])
def test_best_angle_improves_fit_without_turning_north_downward(tilt: float) -> None:
    rectangle = np.array(((-5, -1), (5, -1), (5, 1), (-5, 1)), dtype=float)
    diagonal = peri_scribe.presentation.preview_geometry.rotate(rectangle, tilt)
    angle = peri_scribe.presentation.preview_geometry.best_angle(diagonal)
    fitted = peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, angle)
    north_up = peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, 0)
    assert -math.pi / 2 <= angle <= math.pi / 2
    north = peri_scribe.presentation.preview_geometry.rotate(
        np.array(((0, 1),), dtype=float),
        angle,
    )[0]
    assert north[1] <= 0
    assert fitted > north_up * 1.4
    assert fitted >= max(
        peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, candidate)
        for candidate in np.linspace(0, math.pi, 1001)
    )


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [(-121, 36), (-68, 45), (-156, 20), (179.999, 65)],
)
def test_transform_for_fits_all_parts_in_a_local_metric_projection(
    longitude: float,
    latitude: float,
) -> None:
    geometry = shapely.box(
        longitude - 0.01,
        latitude,
        longitude + 0.01,
        latitude + 0.005,
    )
    if longitude > 0:
        geometry = shapely.transform(
            geometry,
            lambda coordinates: np.column_stack((
                (coordinates[:, 0] + 180) % 360 - 180,
                coordinates[:, 1],
            )),
        )
    transform = peri_scribe.presentation.preview_geometry.transform_for([geometry])
    pixels = np.array(transform.points(geometry.exterior.coords)) / (
        peri_scribe.presentation.preview_geometry.SUPERSAMPLING
    )
    margin = peri_scribe.presentation.preview_geometry.MARGIN
    assert np.all(pixels >= margin - 1e-8)
    assert np.all(pixels <= np.array((128, 72)) - margin + 1e-8)
    assert np.any(np.isclose(np.ptp(pixels, axis=0), np.array((128, 72)) - 2 * margin))


def test_polygons_retains_holes_and_islands_and_ignores_nondrawable_parts() -> None:
    holed = shapely.Polygon(
        ((0, 0), (4, 0), (4, 4), (0, 4)),
        holes=[((1, 1), (2, 1), (2, 2), (1, 2))],
    )
    island = shapely.box(5, 5, 6, 6)
    geometry = shapely.GeometryCollection([
        shapely.MultiPolygon([holed, island]),
        shapely.Point(7, 7),
    ])
    assert peri_scribe.presentation.preview_geometry.polygons(geometry) == (
        holed,
        island,
    )


def test_polygons_ignores_an_empty_polygon() -> None:
    assert peri_scribe.presentation.preview_geometry.polygons(shapely.Polygon()) == ()


@pytest.mark.parametrize("angle", [0, math.pi / 6, math.pi / 2, math.pi * 0.98])
def test_north_dart_has_a_tight_antialiased_black_and_white_outline(
    angle: float,
) -> None:
    dart = peri_scribe.presentation.preview_geometry.north_dart(angle)
    assert dart.getchannel("A").getbbox() == (0, 0, dart.width, dart.height)
    pixels = np.asarray(dart)
    assert np.any(
        np.all(pixels[:, :, :3] > NEAR_WHITE, axis=2) & (pixels[:, :, 3] > NEAR_WHITE),
    )
    assert np.any(np.all(pixels == (0, 0, 0, 255), axis=2))
    assert np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < OPAQUE))
    if angle == 0:
        assert dart.height > dart.width
    elif math.isclose(angle, math.pi / 2):
        assert dart.width > dart.height


def test_draw_map_preserves_holes_solid_fill_outline_order_and_flush_dart() -> None:
    hole = (
        (-121.008, 36.003),
        (-121.004, 36.003),
        (-121.004, 36.007),
        (-121.008, 36.007),
    )
    perimeters = [
        shapely.Polygon(
            shapely.box(-121.01 - step, 36 - step, -121 + step, 36.01 + step).exterior,
            holes=[hole],
        )
        for step in (0, 0.002, 0.004)
    ]
    image = peri_scribe.presentation.preview_geometry.draw_map(
        [(perimeters[-1], "#4488bb")],
        perimeters,
    )
    pixels = np.asarray(image)
    assert image.size == (128, 72)
    for color in ((255, 255, 255), (255, 255, 0), (255, 0, 0), (68, 136, 187)):
        distance = np.linalg.norm(pixels[:, :, :3].astype(float) - color, axis=2)
        assert np.any((distance < MAXIMUM_COLOR_DISTANCE) & (pixels[:, :, 3] == OPAQUE))
    transform = peri_scribe.presentation.preview_geometry.transform_for(
        [perimeters[-1], *perimeters],
    )
    center = transform.points([(-121.006, 36.005)])[0]
    x, y = (round(value / 8) for value in center)
    assert pixels[y, x, 3] == 0
    assert np.any(pixels[0, :, 3] > 0)
    assert np.any(pixels[:, -1, 3] > 0)
    assert np.any(pixels[:, :, 3] == 0)
    assert np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < OPAQUE))
