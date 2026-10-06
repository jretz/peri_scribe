"""Check proportions, per-fire orientation, holes, outlines, and north darts."""

import math

import numpy as np
import pytest
import shapely

import peri_scribe.presentation.preview_geometry
import tests.helpers.factories.peri_scribe.presentation.preview_geometry
import tests.helpers.reference.peri_scribe.presentation.preview_geometry


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
def test_best_fit_angle_maximizes_the_uniform_fit(tilt: float) -> None:
    rectangle = np.array(((-5, -1), (5, -1), (5, 1), (-5, 1)), dtype=float)
    diagonal = peri_scribe.presentation.preview_geometry.rotate(rectangle, tilt)
    angle = peri_scribe.presentation.preview_geometry.best_fit_angle(diagonal)
    fitted = peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, angle)
    north_up = peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, 0)
    assert fitted > north_up * 1.4
    assert fitted >= max(
        peri_scribe.presentation.preview_geometry.fitted_scale(diagonal, candidate)
        for candidate in np.linspace(0, math.pi, 1001)
    )


@pytest.mark.parametrize("tilt", [-0.8, 0.8, math.pi / 2])
def test_best_angle_keeps_north_from_pointing_downward(tilt: float) -> None:
    rectangle = np.array(((-5, -1), (5, -1), (5, 1), (-5, 1)), dtype=float)
    diagonal = peri_scribe.presentation.preview_geometry.rotate(rectangle, tilt)
    angle = peri_scribe.presentation.preview_geometry.best_angle(diagonal)
    assert -math.pi / 2 <= angle < math.pi / 2
    north = peri_scribe.presentation.preview_geometry.rotate(
        np.array(((0, 1),), dtype=float),
        angle,
    )[0]
    assert north[1] <= 0


def test_best_angle_clears_the_dart_for_a_small_reduction_in_map_size() -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    triangle = np.array(((0, 0), (10, 0), (10, 4)), dtype=float)
    fit_angle = peri_scribe.presentation.preview_geometry.best_fit_angle(triangle)
    angle = peri_scribe.presentation.preview_geometry.best_angle(triangle)
    original_overlap = reference.overlap_fraction(triangle, fit_angle)
    selected_overlap = reference.overlap_fraction(triangle, angle)
    substantial_overlap = 0.5
    negligible_overlap = 0.01
    assert original_overlap > substantial_overlap
    assert selected_overlap < negligible_overlap
    assert peri_scribe.presentation.preview_geometry.fitted_scale(triangle, angle) > (
        0.9
        * peri_scribe.presentation.preview_geometry.fitted_scale(triangle, fit_angle)
    )


def test_best_angle_retains_maximum_fit_when_the_dart_is_already_clear() -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    footprint = np.array(((0, 0), (4, 0), (4, 10), (2, 7)), dtype=float)
    fit_angle = peri_scribe.presentation.preview_geometry.best_fit_angle(footprint)
    fit_overlap = reference.overlap_fraction(footprint, fit_angle)
    assert fit_overlap == 0
    angle = peri_scribe.presentation.preview_geometry.best_angle(footprint)
    assert peri_scribe.presentation.preview_geometry.fitted_scale(
        footprint,
        angle,
    ) == pytest.approx(
        peri_scribe.presentation.preview_geometry.fitted_scale(footprint, fit_angle),
    )


def test_best_angle_accepts_small_overlap_to_preserve_a_larger_map() -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    footprint = np.array(((0, 0), (10, 1), (8, 4), (2, 3)), dtype=float)
    fit_angle = peri_scribe.presentation.preview_geometry.best_fit_angle(footprint)
    angle = peri_scribe.presentation.preview_geometry.best_angle(footprint)
    overlap = reference.overlap_fraction(footprint, angle)
    minimum_overlap, maximum_overlap = 0.01, 0.05
    assert minimum_overlap < overlap < maximum_overlap
    assert peri_scribe.presentation.preview_geometry.fitted_scale(footprint, angle) > (
        0.99
        * peri_scribe.presentation.preview_geometry.fitted_scale(footprint, fit_angle)
    )


def test_best_angle_finds_narrow_clearance_optimum_for_brushy_canyon() -> None:
    factories = tests.helpers.factories.peri_scribe.presentation.preview_geometry
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    footprint = factories.brushy_canyon_hull()
    fit_angle = peri_scribe.presentation.preview_geometry.best_fit_angle(footprint)
    maximum_scale = peri_scribe.presentation.preview_geometry.fitted_scale(
        footprint,
        fit_angle,
    )
    angle = peri_scribe.presentation.preview_geometry.best_angle(footprint)
    known_candidate = math.radians(-68.62028)
    selected_score, known_score = (
        peri_scribe.presentation.preview_geometry.fitted_scale(footprint, candidate)
        / maximum_scale
        - 0.75 * reference.overlap_fraction(footprint, candidate)
        for candidate in (angle, known_candidate)
    )
    assert selected_score >= known_score - 1e-8


def test_best_angle_is_invariant_to_footprint_units_and_origin() -> None:
    footprint = np.array(((0, 0), (10, 0), (10, 4)), dtype=float)
    translated = footprint * 1000 + np.array((1_000_000, -2_000_000))
    angle = peri_scribe.presentation.preview_geometry.best_angle(footprint)
    translated_angle = peri_scribe.presentation.preview_geometry.best_angle(translated)
    assert translated_angle == pytest.approx(angle, abs=1e-7)


@pytest.mark.parametrize("coordinates", [((0, 0),), ((0, 0), (10, 4))])
def test_best_angle_accepts_footprint_hulls_without_polygon_area(
    coordinates: tuple[tuple[int, int], ...],
) -> None:
    footprint = np.array(coordinates, dtype=float)
    angle = peri_scribe.presentation.preview_geometry.best_angle(footprint)
    assert angle == pytest.approx(
        peri_scribe.presentation.preview_geometry.best_fit_angle(footprint),
    )


@pytest.mark.parametrize("angle", [-math.pi / 2, -0.37, 0, math.pi / 6])
def test_angle_candidate_measures_overlap_at_the_final_rendered_orientation(
    angle: float,
) -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    footprint = np.array(((0, 0), (10, 0), (10, 4)), dtype=float)
    candidate = peri_scribe.presentation.preview_geometry.angle_candidate(
        footprint,
        math.degrees(angle),
        peri_scribe.presentation.preview_geometry.north_dart_hull(angle),
    )
    assert candidate.overlap == pytest.approx(
        reference.overlap_fraction(footprint, angle),
    )


def test_refinement_seeds_retains_distinct_starts_when_fewer_are_available() -> None:
    reference = peri_scribe.presentation.preview_geometry.AngleCandidate(
        degrees=15,
        scale=1,
        overlap=0.4,
    )
    strongest = peri_scribe.presentation.preview_geometry.AngleCandidate(
        degrees=-10,
        scale=1,
        overlap=0.1,
    )
    nearby = peri_scribe.presentation.preview_geometry.AngleCandidate(
        degrees=-9.5,
        scale=1,
        overlap=0.2,
    )
    separate = peri_scribe.presentation.preview_geometry.AngleCandidate(
        degrees=30,
        scale=0.98,
        overlap=0.3,
    )
    result = peri_scribe.presentation.preview_geometry.refinement_seeds(
        [nearby, separate, strongest],
        0.75,
        1,
        reference,
    )
    assert result == [strongest, separate, reference]


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


@pytest.mark.parametrize("angle", [-math.pi / 2, -0.37, 0, math.pi / 6, math.pi / 2])
def test_north_dart_hull_includes_rendered_pixel_squares_and_two_pixel_clearance(
    angle: float,
) -> None:
    reference = tests.helpers.reference.peri_scribe.presentation.preview_geometry
    hull = peri_scribe.presentation.preview_geometry.north_dart_hull(angle)
    expected = reference.rendered_dart_hull(angle)
    assert hull.symmetric_difference(expected).area == pytest.approx(0, abs=1e-9)
    assert hull.bounds[1] == pytest.approx(-2)
    assert hull.bounds[2] == pytest.approx(130)


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
