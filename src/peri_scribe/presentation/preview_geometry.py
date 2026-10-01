"""Draw small, proportionate fire maps with a north dart on transparent backgrounds."""

from __future__ import annotations

import dataclasses
import math
import typing

import numpy as np
import numpy.typing as npt
import PIL.Image
import PIL.ImageDraw
import pyproj
import shapely


if typing.TYPE_CHECKING:
    import collections.abc


type Coordinates = npt.NDArray[np.float64]
SIZE = (128, 72)
SUPERSAMPLING = 8
MARGIN = 2
OUTLINE_COLORS = ("#ffffff", "#ffff00", "#ff0000")
DART_VERTICES = ((0, -9), (5, 9), (0, 6), (-5, 9))


@dataclasses.dataclass(frozen=True, kw_only=True)
class Transform:
    """Share a uniform geographic scale and rotation with the north dart."""

    projection: pyproj.Transformer
    angle: float
    scale: float
    offset: tuple[float, float]

    def points(
        self,
        coordinates: collections.abc.Sequence,
    ) -> list[tuple[float, float]]:
        """Preserve subpixel geography until the antialiasing pass.

        Args:
            coordinates: Longitude/latitude coordinates from a polygon ring.

        Returns:
            Coordinates on the supersampled drawing canvas.
        """
        longitude, latitude = np.asarray(coordinates).T[:2]
        east, north = self.projection.transform(longitude, latitude)
        rotated = rotate(np.column_stack((east, north)), self.angle)
        pixels = (rotated * self.scale + self.offset) * SUPERSAMPLING
        return list(map(tuple, pixels.tolist()))


def rotate(coordinates: Coordinates, angle: float) -> Coordinates:
    """Orient metric coordinates in screen axes without stretching the fire.

    Args:
        coordinates: East/north coordinates in the projection's native meters.
        angle: Counterclockwise map rotation in radians.

    Returns:
        Rotated coordinates with screen y increasing downward.
    """
    cosine, sine = math.cos(angle), math.sin(angle)
    return coordinates @ np.array(((cosine, -sine), (-sine, -cosine)))


def fitted_scale(coordinates: Coordinates, angle: float) -> float:
    """Fit the entire fire footprint inside the antialiasing margin.

    Args:
        coordinates: Vertices of the projected footprint's convex hull.
        angle: Candidate map rotation in radians.

    Returns:
        Uniform pixels per native projected meter.
    """
    extent = np.ptp(rotate(coordinates, angle), axis=0)
    available = np.array(SIZE) - 2 * MARGIN
    return float(np.min(available / np.maximum(extent, np.finfo(float).eps)))


def best_angle(coordinates: Coordinates) -> float:
    """Search every orientation before refining the best fit for this fire.

    Opposite orientations have the same bounds; ties prefer the rotation nearest north
    up within ±90 degrees. The initial quarter-degree search covers the whole half-turn,
    followed by five increasingly fine local searches (to 0.0000025 degrees).

    Args:
        coordinates: Vertices of the projected footprint's convex hull.

    Returns:
        The best sampled rotation in radians, between -π/2 and π/2.
    """
    step = math.pi / 720
    angles = np.arange(720) * step
    angle = 0.0
    for _ in range(6):
        scales = np.array([fitted_scale(coordinates, float(value)) for value in angles])
        angle = float(angles[int(np.argmax(scales))])
        angles = angle + np.arange(-10, 11) * (step / 10)
        step /= 10
    return (angle + math.pi / 2) % math.pi - math.pi / 2


def transform_for(geometries: collections.abc.Sequence[shapely.Geometry]) -> Transform:
    """Use a fire-centered metric projection throughout the United States.

    Args:
        geometries: All filled rings and outlined perimeters, in longitude/latitude.

    Returns:
        The rotation, uniform fit, and centered placement for this fire.
    """
    coordinates = shapely.get_coordinates(geometries)
    # A spherical center keeps fires crossing the antimeridian local in Alaska.
    longitude = np.radians(coordinates[:, 0])
    center_longitude = math.degrees(
        math.atan2(
            float(np.mean(np.sin(longitude))),
            float(np.mean(np.cos(longitude))),
        ),
    )
    center_latitude = float(np.mean(coordinates[:, 1]))
    projection = pyproj.Transformer.from_crs(
        "EPSG:4326",
        f"+proj=aeqd +lat_0={center_latitude} +lon_0={center_longitude} "
        "+datum=WGS84 +units=m",
        always_xy=True,
    )
    east, north = projection.transform(coordinates[:, 0], coordinates[:, 1])
    hull = shapely.MultiPoint(np.column_stack((east, north))).convex_hull
    projected = shapely.get_coordinates(hull)
    angle = best_angle(projected)
    scale = fitted_scale(projected, angle)
    rotated = rotate(projected, angle)
    center = (np.min(rotated, axis=0) + np.max(rotated, axis=0)) / 2
    offset = np.array(SIZE) / 2 - center * scale
    return Transform(
        projection=projection,
        angle=angle,
        scale=scale,
        offset=(float(offset[0]), float(offset[1])),
    )


def polygons(geometry: shapely.Geometry) -> tuple[shapely.Polygon, ...]:
    """Keep multipart islands and polygon holes while ignoring nondrawable parts.

    Args:
        geometry: A complete perimeter or growth ring.

    Returns:
        Its nonempty polygon parts.
    """
    if isinstance(geometry, shapely.Polygon):
        return () if geometry.is_empty else (geometry,)
    if isinstance(geometry, shapely.MultiPolygon | shapely.GeometryCollection):
        return tuple(polygon for part in geometry.geoms for polygon in polygons(part))
    return ()


def north_dart(angle: float) -> PIL.Image.Image:
    """Retain the full antialiased outline in a tightly cropped 18-pixel dart.

    Args:
        angle: The map rotation in radians.

    Returns:
        A north-pointing black/white dart, ready for top/right edge placement.
    """
    padded_size = 64
    high = PIL.Image.new(
        "RGBA",
        (padded_size * SUPERSAMPLING, padded_size * SUPERSAMPLING),
    )
    cosine, sine = math.cos(angle), math.sin(angle)
    points = [
        (
            (padded_size / 2 + cosine * x + sine * y) * SUPERSAMPLING,
            (padded_size / 2 - sine * x + cosine * y) * SUPERSAMPLING,
        )
        for x, y in DART_VERTICES
    ]
    tip, right, notch, left = points
    drawing = PIL.ImageDraw.Draw(high)
    drawing.polygon((tip, notch, left), fill="white")
    drawing.polygon((tip, right, notch), fill="black")
    outline = [*points, tip]
    drawing.line(outline, fill="white", width=round(1.4 * SUPERSAMPLING), joint="curve")
    drawing.line(
        outline,
        fill="black",
        width=round(0.65 * SUPERSAMPLING),
        joint="curve",
    )
    padded = high.resize((padded_size, padded_size), PIL.Image.Resampling.LANCZOS)
    return padded.crop(padded.getchannel("A").getbbox())


def draw_map(
    fills: collections.abc.Sequence[tuple[shapely.Geometry, str]],
    perimeters: collections.abc.Sequence[shapely.Geometry],
) -> PIL.Image.Image:
    """Draw opaque KMZ rings beneath up to three complete antialiased outlines.

    Args:
        fills: Chronological growth-ring geometries and their KMZ fill colors.
        perimeters: The latest three full perimeters, oldest first.

    Returns:
        A transparent native-size map with a dart touching its top and right edges.
    """
    transform = transform_for([*(geometry for geometry, _ in fills), *perimeters])
    high_size = (SIZE[0] * SUPERSAMPLING, SIZE[1] * SUPERSAMPLING)
    high = PIL.Image.new("RGBA", high_size)
    for geometry, color in fills:
        mask = PIL.Image.new("L", high_size)
        drawing = PIL.ImageDraw.Draw(mask)
        for polygon in polygons(geometry):
            drawing.polygon(transform.points(polygon.exterior.coords), fill=255)
            for hole in polygon.interiors:
                drawing.polygon(transform.points(hole.coords), fill=0)
        high.paste(color, (0, 0, *high_size), mask)
    drawing = PIL.ImageDraw.Draw(high)
    for geometry, color in zip(
        perimeters,
        OUTLINE_COLORS[-len(perimeters) :],
        strict=True,
    ):
        for polygon in polygons(geometry):
            for ring in (polygon.exterior, *polygon.interiors):
                drawing.line(
                    transform.points(ring.coords),
                    fill=color,
                    width=SUPERSAMPLING,
                    joint="curve",
                )
    image = high.resize(SIZE, PIL.Image.Resampling.LANCZOS)
    dart = north_dart(transform.angle)
    image.alpha_composite(dart, (SIZE[0] - dart.width, 0))
    return image
