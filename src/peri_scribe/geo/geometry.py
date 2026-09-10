"""Shapely geometry helpers shared across the package.

These are the operations more than one package area needs and no single one owns. They
work on shapely geometries alone, so nothing that measures or cleans a geometry has to
depend on the area that happens to use it first.
"""

from __future__ import annotations

import typing

import numpy as np
import shapely


if typing.TYPE_CHECKING:
    import pyproj


def transform_coordinates(
    geometry: shapely.Geometry,
    transformer: pyproj.Transformer,
) -> shapely.Geometry:
    """Return *geometry* with every coordinate passed through *transformer*.

    The coordinates are handed to the transformer in one vectorized call rather than a
    point at a time, and a z coordinate is carried through when the geometry has one.

    Args:
        geometry: The geometry to transform.
        transformer: The transformer to apply to its coordinates.

    Returns:
        The transformed geometry.
    """
    if shapely.has_z(geometry):
        return shapely.transform(
            geometry,
            lambda coordinates: np.column_stack(
                transformer.transform(
                    coordinates[:, 0],
                    coordinates[:, 1],
                    coordinates[:, 2],
                ),
            ),
            include_z=True,
        )
    return shapely.transform(
        geometry,
        lambda coordinates: np.column_stack(
            transformer.transform(coordinates[:, 0], coordinates[:, 1]),
        ),
    )


def polygonal_parts(geometry: shapely.Geometry) -> list[shapely.Polygon]:
    """Return *geometry*'s polygon parts, flattening every collection level.

    A polygon part may arrive directly, as a multi-polygon's member, or as a
    multi-polygon nested inside a collection, so each level is unwrapped and
    non-polygonal members are dropped.

    Args:
        geometry: The geometry to flatten.

    Returns:
        Every non-empty polygon part, in order, or an empty list when the geometry has
        none.
    """
    parts: list[shapely.Polygon] = []
    for part in shapely.get_parts(geometry):
        if part.is_empty:
            continue
        if part.geom_type == "Polygon":
            parts.append(typing.cast("shapely.Polygon", part))
        elif part.geom_type == "MultiPolygon":
            parts.extend(
                typing.cast("shapely.Polygon", member)
                for member in part.geoms
                if not member.is_empty
            )
    return parts
