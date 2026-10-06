"""Measure thumbnail collisions using rendered pixels and geometric transforms."""

import math

import numpy as np
import numpy.typing as npt
import shapely
import shapely.affinity

import peri_scribe.presentation.preview_geometry


def rendered_dart_hull(angle: float) -> shapely.Geometry:
    """Include pixel extents and clearance outside the image boundary.

    Args:
        angle: The map rotation in radians.

    Returns:
        The convex hull of occupied dart pixel squares, with two pixels of clearance.
    """
    dart = peri_scribe.presentation.preview_geometry.north_dart(angle)
    vertical, horizontal = np.nonzero(np.asarray(dart.getchannel("A")))
    horizontal += peri_scribe.presentation.preview_geometry.SIZE[0] - dart.width
    pixels = shapely.box(horizontal, vertical, horizontal + 1, vertical + 1)
    return shapely.union_all(pixels).convex_hull.buffer(2)


def fitted_map_hull(
    coordinates: npt.NDArray[np.float64],
    angle: float,
) -> shapely.Geometry:
    """Fit the candidate in screen space independently of the thumbnail transform.

    Args:
        coordinates: Vertices of a footprint in east/north coordinates.
        angle: The map rotation in radians.

    Returns:
        The uniformly fitted footprint hull centered in the thumbnail.
    """
    geometry = shapely.affinity.rotate(
        shapely.MultiPoint(coordinates).convex_hull,
        math.degrees(angle),
        origin=(0, 0),
    )
    minimum_x, minimum_y, maximum_x, maximum_y = geometry.bounds
    width, height = peri_scribe.presentation.preview_geometry.SIZE
    margin = peri_scribe.presentation.preview_geometry.MARGIN
    scale = min(
        (width - 2 * margin) / (maximum_x - minimum_x),
        (height - 2 * margin) / (maximum_y - minimum_y),
    )
    geometry = shapely.affinity.scale(
        geometry,
        xfact=scale,
        yfact=-scale,
        origin=(0, 0),
    )
    return shapely.affinity.translate(
        geometry,
        xoff=width / 2 - (minimum_x + maximum_x) * scale / 2,
        yoff=height / 2 + (minimum_y + maximum_y) * scale / 2,
    )


def overlap_fraction(coordinates: npt.NDArray[np.float64], angle: float) -> float:
    """Measure the portion of the arrow's full clearance hull covered by the map.

    Args:
        coordinates: Vertices of a footprint in east/north coordinates.
        angle: The map rotation in radians.

    Returns:
        The intersection area divided by the complete buffered dart hull area.
    """
    dart = rendered_dart_hull(angle)
    return fitted_map_hull(coordinates, angle).intersection(dart).area / dart.area
