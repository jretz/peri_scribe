"""Draw small, proportionate fire maps with a north dart on transparent backgrounds."""

from __future__ import annotations

import dataclasses
import functools
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
DART_CLEARANCE = 2
OVERLAP_WEIGHT = 0.75
ANGLE_STEP = 0.025
REFINEMENT_STARTS = 6
SCORE_TOLERANCE = 1e-11
MINIMUM_ANGLE = -90.0
MAXIMUM_ANGLE = 90.0
MINIMUM_POLYGON_POINTS = 3


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


def best_fit_angle(coordinates: Coordinates) -> float:
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


def centered_offset(coordinates: Coordinates, scale: float) -> Coordinates:
    """Keep a fitted footprint centered independently of the dart's corner anchor.

    Args:
        coordinates: Rotated footprint coordinates in screen axes.
        scale: Uniform pixels per native projected meter.

    Returns:
        The native-pixel translation needed to center the footprint.
    """
    center = (np.min(coordinates, axis=0) + np.max(coordinates, axis=0)) / 2
    return np.array(SIZE) / 2 - center * scale


@dataclasses.dataclass(frozen=True, kw_only=True)
class AngleCandidate:
    """Compare linear size and dart obstruction independently of a fire's acreage."""

    degrees: float
    scale: float
    overlap: float

    def score(self, weight: float, maximum_scale: float) -> float:
        """Charge a linear size penalty for the fraction of obstructed dart hull.

        Args:
            weight: Size penalty for completely covering the buffered dart hull.
            maximum_scale: Largest sampled uniform fit for this footprint.

        Returns:
            Normalized linear size minus weighted overlap.
        """
        return self.scale / maximum_scale - weight * self.overlap


def angle_candidate(
    coordinates: Coordinates,
    degrees: float,
    dart_hull: shapely.Polygon,
) -> AngleCandidate:
    """Measure obstruction at the same scale and anchors used by the renderer.

    Args:
        coordinates: Vertices of the projected footprint's convex hull.
        degrees: Candidate rotation in degrees within the allowable half-turn.
        dart_hull: Placed dart hull including the clearance zone.

    Returns:
        The fitted linear scale and fraction of the full buffered dart hull covered.
    """
    angle = math.radians(degrees)
    scale = fitted_scale(coordinates, angle)
    rotated = rotate(coordinates, angle)
    points = rotated * scale + centered_offset(rotated, scale)
    footprint = (
        shapely.Polygon(points)
        if len(points) >= MINIMUM_POLYGON_POINTS
        else shapely.MultiPoint(points)
    )
    overlap = footprint.intersection(dart_hull).area / dart_hull.area
    return AngleCandidate(degrees=degrees, scale=scale, overlap=overlap)


def select_angle(
    candidates: collections.abc.Sequence[AngleCandidate],
    weight: float,
    maximum_scale: float,
    reference: AngleCandidate,
) -> AngleCandidate:
    """Keep equivalent scores from needlessly changing the largest-fit orientation.

    Args:
        candidates: At least one fitted candidate in the allowed angle range.
        weight: Linear dart-obstruction penalty.
        maximum_scale: Largest sampled uniform fit for this footprint.
        reference: Preferred orientation for numerically equivalent scores.

    Returns:
        Highest-scoring candidate, with deterministic ties nearest the reference.
    """
    maximum = max(value.score(weight, maximum_scale) for value in candidates)
    return min(
        (
            value
            for value in candidates
            if value.score(weight, maximum_scale) >= maximum - SCORE_TOLERANCE
        ),
        key=lambda value: (
            abs(value.degrees - reference.degrees),
            abs(value.degrees),
            value.degrees,
        ),
    )


def refinement_seeds(
    candidates: collections.abc.Sequence[AngleCandidate],
    weight: float,
    maximum_scale: float,
    reference: AngleCandidate,
) -> list[AngleCandidate]:
    """Retain competing orientations across jumps in the rendered dart's support.

    Args:
        candidates: Coarse samples spanning the allowed half-turn.
        weight: Linear dart-obstruction penalty.
        maximum_scale: Largest sampled uniform fit for this footprint.
        reference: Largest-fit orientation retained as an additional start.

    Returns:
        Leading starts separated by at least one degree, plus the reference.
    """
    ranked = sorted(
        candidates,
        key=lambda value: value.score(weight, maximum_scale),
        reverse=True,
    )
    seeds: list[AngleCandidate] = []
    for value in ranked:
        if all(abs(value.degrees - seed.degrees) >= 1 for seed in seeds):
            seeds.append(value)
            if len(seeds) == REFINEMENT_STARTS:
                break
    return [*seeds, reference]


def refine_angle(
    coordinates: Coordinates,
    candidates: dict[float, AngleCandidate],
    seed: AngleCandidate,
    *,
    weight: float,
    maximum_scale: float,
    reference: AngleCandidate,
) -> None:
    """Resolve small clearance changes without wrapping to a different corner layout.

    Args:
        coordinates: Vertices of the projected footprint's convex hull.
        candidates: Shared measurements extended by this local search.
        seed: Starting orientation.
        weight: Linear dart-obstruction penalty.
        maximum_scale: Largest sampled uniform fit for this footprint.
        reference: Preferred orientation for numerically equivalent scores.
    """
    current = seed
    step = ANGLE_STEP
    for _ in range(4):
        local = [current]
        for delta in range(-10, 11):
            degrees = float(round(current.degrees + delta * step / 10, 10))
            if MINIMUM_ANGLE <= degrees < MAXIMUM_ANGLE:
                if degrees not in candidates:
                    candidates[degrees] = angle_candidate(
                        coordinates,
                        degrees,
                        north_dart_hull(math.radians(degrees)),
                    )
                local.append(candidates[degrees])
        current = select_angle(local, weight, maximum_scale, reference)
        step /= 10


def best_angle(coordinates: Coordinates) -> float:
    """Balance map size and north-dart clearance throughout the allowable half-turn.

    Args:
        coordinates: Vertices of a nonempty projected footprint's convex hull.

    Returns:
        The best sampled size-minus-overlap rotation in radians, in [-π/2, π/2).
    """
    reference_angle = best_fit_angle(coordinates)
    reference = angle_candidate(
        coordinates,
        math.degrees(reference_angle),
        north_dart_hull(reference_angle),
    )
    if reference.overlap == 0:
        return reference_angle
    candidates = {reference.degrees: reference}
    for degrees, hull in coarse_dart_hulls():
        candidates[degrees] = angle_candidate(coordinates, degrees, hull)
    coarse = list(candidates.values())
    maximum_scale = max(value.scale for value in coarse)
    # Nearby penalties expose narrow clearance optima at raster-support boundaries.
    for weight in (0.0, 0.5, OVERLAP_WEIGHT, 1.0):
        for seed in refinement_seeds(coarse, weight, maximum_scale, reference):
            refine_angle(
                coordinates,
                candidates,
                seed,
                weight=weight,
                maximum_scale=maximum_scale,
                reference=reference,
            )
    values = list(candidates.values())
    maximum_scale = max(value.scale for value in values)
    return math.radians(
        select_angle(values, OVERLAP_WEIGHT, maximum_scale, reference).degrees,
    )


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
    offset = centered_offset(rotated, scale)
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


@functools.lru_cache(maxsize=4096)
def north_dart_hull(angle: float) -> shapely.Polygon:
    """Give even antialiased dart pixels two pixels of breathing room.

    Args:
        angle: Map rotation in radians.

    Returns:
        The placed alpha-support hull, buffered without clipping to the canvas.
    """
    dart = north_dart(angle)
    rows, columns = np.nonzero(np.asarray(dart.getchannel("A")))
    centers = np.column_stack((columns + SIZE[0] - dart.width + 0.5, rows + 0.5))
    boundary = shapely.get_coordinates(shapely.MultiPoint(centers).convex_hull)
    squares = np.concatenate([
        boundary + corner
        for corner in ((-0.5, -0.5), (-0.5, 0.5), (0.5, -0.5), (0.5, 0.5))
    ])
    return shapely.MultiPoint(squares).convex_hull.buffer(DART_CLEARANCE)


@functools.cache
def coarse_dart_hulls() -> tuple[tuple[float, shapely.Polygon], ...]:
    """Share the fixed search grid without fine-search cache eviction between fires.

    Returns:
        Degree angles and their placed dart hulls spanning [-90, 90).
    """
    degrees = [
        float(round(value, 9))
        for value in np.arange(MINIMUM_ANGLE, MAXIMUM_ANGLE, ANGLE_STEP)
    ]
    degrees.append(float(np.nextafter(MAXIMUM_ANGLE, -np.inf)))
    return tuple((value, north_dart_hull(math.radians(value))) for value in degrees)


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
