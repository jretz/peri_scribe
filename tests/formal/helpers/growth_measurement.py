"""Separate exact surface policy from its numerical polygon-area inputs."""

import itertools
import typing

import numpy as np
import shapely

import spatial_data.surface_measurements


CELL_COUNT = 4
AREA_SCALE = 1_000_000
AREA_TOLERANCE = 0.0001


def cells() -> tuple[shapely.Polygon, ...]:
    """Keep coverage edges on a binary lattice at varied United States latitudes.

    Returns:
        Four disjoint real polygons whose boundaries survive the growth grid exactly.
    """
    return tuple(
        shapely.box(
            -160 + cell * 8,
            20 + cell * 16,
            -160 + cell * 8 + 2**-10,
            20 + cell * 16 + 2**-10,
        )
        for cell in range(CELL_COUNT)
    )


def footprint(mask: int) -> shapely.Geometry:
    """Realize an exact cell mask without adding geodesic edge assumptions.

    Args:
        mask: Four-bit membership in the fixed polygon population.

    Returns:
        The polygon union represented by the mask, including an empty union.
    """
    return shapely.union_all([
        cell for index, cell in enumerate(cells()) if mask & (1 << index)
    ])


def histories() -> tuple[tuple[int, ...], ...]:
    """Exhaust short coverage histories and retain longer overlapping revisits.

    Returns:
        Complete short histories and seeded histories over all four cells.
    """
    cases = [
        history
        for length in range(4)
        for history in itertools.product(range(8), repeat=length)
    ]
    cases.extend([
        (15, 15, 15),
        (1, 3, 7, 15, 1, 0, 15),
        (1, 2, 4, 8, 15, 0, 8, 4, 2, 1),
        (15, 7, 3, 1, 0),
    ])
    generator = np.random.default_rng(20261020)
    cases.extend(
        tuple(map(int, generator.integers(0, 16, int(generator.integers(1, 10)))))
        for _ in range(50)
    )
    return tuple(cases)


def weights() -> tuple[int, ...]:
    """Supply measured polygon weights to the exact additive policy abstraction.

    These inputs do not establish the numerical accuracy of the surface integral.
    Ordinary numerical regressions exercise that independent obligation.

    Returns:
        Nonnegative polygon weights in integer millionths of a square meter.
    """
    return tuple(
        round(
            spatial_data.surface_measurements.area(cell).m_as("meters ** 2")
            * AREA_SCALE,
        )
        for cell in cells()
    )


def command(history: tuple[int, ...], areas: tuple[int, ...]) -> str:
    """Keep cumulative expectations tied to the executable proved definitions.

    Args:
        history: The ordered footprint masks.
        areas: The exact model's integer surface weights.

    Returns:
        An oracle request for each cumulative coverage change.
    """
    return " ".join([
        "growth-areas",
        ",".join(map(str, areas)),
        *map(str, history),
    ])


def mixed_geometries() -> tuple[shapely.Geometry, ...]:
    """Give nonpolygon coordinates enough enclosed area to expose accidental closure.

    Returns:
        Polygon, empty, line, point, and recursively mixed collection geometries.
    """
    first, second, *_rest = cells()
    line = shapely.LineString([(-120, 40), (-119, 40), (-119, 41)])
    reversed_line = shapely.reverse(line)
    ring = shapely.LinearRing(line.coords)
    point = shapely.Point(-120, 40)
    hole = shapely.box(
        first.bounds[0] + 2**-12,
        first.bounds[1] + 2**-12,
        first.bounds[2] - 2**-12,
        first.bounds[3] - 2**-12,
    )
    perforated = shapely.Polygon(first.exterior, [hole.exterior.coords])
    return (
        first,
        point,
        line,
        reversed_line,
        ring,
        shapely.GeometryCollection(),
        shapely.MultiPoint([point, shapely.Point(-119, 41)]),
        shapely.MultiLineString([line, reversed_line]),
        shapely.GeometryCollection([first, line, point]),
        shapely.GeometryCollection([line, first, reversed_line, second]),
        shapely.GeometryCollection([
            perforated,
            shapely.GeometryCollection([reversed_line, second, point]),
        ]),
        shapely.GeometryCollection([
            shapely.reverse(perforated),
            shapely.MultiPolygon([second]),
            shapely.GeometryCollection([line, point]),
        ]),
    )


def geometry_tokens(geometry: shapely.Geometry) -> tuple[str, ...]:
    """Only polygon leaf measurements enter the exact filtering abstraction.

    Args:
        geometry: A real geometry whose nested grouping is retained by binary nodes.

    Returns:
        Postfix tokens for the proved polygon-only collection policy.
    """
    if isinstance(geometry, shapely.Polygon):
        contribution = round(
            spatial_data.surface_measurements.area(geometry).m_as("meters ** 2")
            * AREA_SCALE,
        )
        return (f"p,{contribution}",)
    if isinstance(geometry, shapely.GeometryCollection | shapely.MultiPolygon):
        tokens = ("n,0",)
        for part in typing.cast("typing.Iterable[shapely.Geometry]", geometry.geoms):
            tokens += (*geometry_tokens(part), "c")
        return tokens
    return ("n,-999999999999999",)
