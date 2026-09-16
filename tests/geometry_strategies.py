"""Construct valid, bounded geography for generated calculation tests."""

from __future__ import annotations

import typing

import hypothesis.strategies
import shapely
import shapely.affinity


@hypothesis.strategies.composite
def nested_collections(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[shapely.Geometry, list[shapely.Polygon]]:
    """Keep polygon order observable through arbitrary non-polygonal collection layers.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A nested collection and the polygon parts it must retain in traversal order.
    """
    polygons_to_wrap = draw(hypothesis.strategies.lists(polygons(), max_size=5))
    members = []
    for polygon in polygons_to_wrap:
        member: shapely.Geometry = polygon
        for _level in range(draw(hypothesis.strategies.integers(0, 4))):
            member = shapely.GeometryCollection([
                shapely.Point(0, 0),
                member,
                shapely.Polygon(),
            ])
        members.append(member)
    return shapely.GeometryCollection(members), polygons_to_wrap


@hypothesis.strategies.composite
def local_shapes(draw: hypothesis.strategies.DrawFn) -> shapely.Geometry:
    """Exercise bounding-box false positives as well as touching and overlapping shapes.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A point, triangle, or polygon with a hole on a shared coordinate grid.
    """
    left = draw(hypothesis.strategies.integers(0, 5))
    bottom = draw(hypothesis.strategies.integers(0, 5))
    shapes = (
        shapely.Point(left, bottom),
        shapely.Polygon([(left, bottom), (left + 2, bottom), (left, bottom + 2)]),
        shapely.Polygon(
            shapely.box(left, bottom, left + 3, bottom + 3).exterior,
            [shapely.box(left + 1, bottom + 1, left + 2, bottom + 2).exterior],
        ),
    )
    return draw(hypothesis.strategies.sampled_from(shapes))


@hypothesis.strategies.composite
def polygons(draw: hypothesis.strategies.DrawFn) -> shapely.Polygon:
    """Vary footprint shape, holes, winding, scale, and geographic location.

    Convex shells and strictly interior holes avoid rejecting arbitrary invalid rings.
    Coordinates stay away from projection singularities and the antimeridian.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A nonempty WGS84 polygon with an optional asymmetric hole.
    """
    grid = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.integers(0, 100),
                hypothesis.strategies.integers(0, 100),
            ),
            max_size=8,
        ),
    )
    shell = typing.cast(
        "shapely.Polygon",
        shapely.MultiPoint([(0, 0), (100, 0), (0, 100), *grid]).convex_hull,
    )
    if draw(hypothesis.strategies.booleans()):
        center = shell.centroid
        hole = [
            (center.x, center.y),
            *[
                ((center.x + x) / 2, (center.y + y) / 2)
                for x, y in list(shell.exterior.coords)[:2]
            ],
        ]
        shell = shapely.Polygon(shell.exterior, [hole])
    if draw(hypothesis.strategies.booleans()):
        shell = shapely.reverse(shell)
    width = draw(hypothesis.strategies.floats(0.00001, 1.0))
    height = draw(hypothesis.strategies.floats(0.00001, 1.0))
    longitude = draw(hypothesis.strategies.floats(-170, 170))
    latitude = draw(hypothesis.strategies.floats(-70, 70))
    scaled = shapely.affinity.scale(
        shell,
        xfact=width / 100,
        yfact=height / 100,
        origin=(0, 0),
    )
    return shapely.affinity.translate(scaled, xoff=longitude, yoff=latitude)


@hypothesis.strategies.composite
def footprints(
    draw: hypothesis.strategies.DrawFn,
) -> shapely.Polygon | shapely.MultiPolygon:
    """Exercise single and multiple parts without overlapping polygon interiors.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A WGS84 footprint with one or two disjoint polygon parts.
    """
    first = draw(polygons())
    if draw(hypothesis.strategies.booleans()):
        second = shapely.affinity.translate(first, xoff=2)
        return shapely.MultiPolygon([first, second])
    return first


@hypothesis.strategies.composite
def rectangles(draw: hypothesis.strategies.DrawFn) -> shapely.Polygon:
    """Use a shared local grid to exercise overlapping and disjoint fire histories.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A nonempty rectangle in WGS84 coordinates.
    """
    left = draw(hypothesis.strategies.integers(0, 10))
    bottom = draw(hypothesis.strategies.integers(0, 10))
    width = draw(hypothesis.strategies.integers(1, 10))
    height = draw(hypothesis.strategies.integers(1, 10))
    return shapely.box(
        -100 + left / 100,
        40 + bottom / 100,
        -100 + (left + width) / 100,
        40 + (bottom + height) / 100,
    )


@hypothesis.strategies.composite
def disjoint_coverage_sequences(
    draw: hypothesis.strategies.DrawFn,
) -> list[shapely.Polygon]:
    """Make area conservation independent of overlay-induced geodesic edge changes.

    Disjoint components retain their original edges after union. Repeated observations
    still exercise winding changes and the distinction between area and added area.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A sequence of disjoint rectangles, including possible repeated components.
    """
    rectangles_to_place = draw(
        hypothesis.strategies.lists(rectangles(), min_size=1, max_size=5),
    )
    catalog = [
        shapely.affinity.translate(rectangle, xoff=index)
        for index, rectangle in enumerate(rectangles_to_place)
    ]
    return draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.sampled_from(catalog),
            max_size=12,
        ),
    )
