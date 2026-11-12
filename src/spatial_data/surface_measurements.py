"""Measure polygon sets bounded by straight WGS84 longitude/latitude segments.

See [Growth geometry and area] for the surface integral, numerical limits, and
coordinate interpretation.

[Growth geometry and area]: ../../docs/algorithms/growth-geometry-and-area.md
"""

from __future__ import annotations

import collections.abc
import math
import typing

import numpy as np
import numpy.typing as npt
import shapely

from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


WGS84_EQUATORIAL_RADIUS = 6_378_137 * units.meters
WGS84_FLATTENING = 1 / 298.257223563
ECCENTRICITY_SQUARED = WGS84_FLATTENING * (2 - WGS84_FLATTENING)
ECCENTRICITY = math.sqrt(ECCENTRICITY_SQUARED)
SURFACE_SCALE = WGS84_EQUATORIAL_RADIUS**2 * (1 - ECCENTRICITY_SQUARED) / 2
SQUARE_METERS = SURFACE_SCALE.units
DEGREES = units.degrees
RADIANS = units.radians
DEGREE_TO_RADIAN = (1 * DEGREES).m_as(RADIANS)
GAUSSIAN_NODES, GAUSSIAN_WEIGHTS = np.polynomial.legendre.leggauss(8)
GAUSSIAN_MEAN_WEIGHTS = GAUSSIAN_WEIGHTS / 2
MAXIMUM_INTEGRATION_BATCH_PIECES = 8192

type Coordinates = npt.NDArray[np.float64]


def area(geometry: shapely.Geometry) -> pint.Quantity[float]:
    """Measure polygon leaves on the WGS84 surface beneath their coordinate edges.

    Inputs are valid geometries with finite WGS84 coordinates and latitude between
    -90 and 90 degrees. Longitude follows the raw coordinate-plane edge, including
    an edge spanning the antimeridian. Polygon collection members must have disjoint
    interiors to describe covered ground without multiplicity. Points and lines,
    including standalone linear rings, contribute zero.

    Args:
        geometry: The polygon set in longitude and latitude degrees.

    Returns:
        Polygon surface area in square meters, independent of ring winding.
    """
    measurements = iter(ring_areas(tuple(polygon_rings(geometry))))
    return area_from_ring_areas(geometry, measurements)


def polygon_rings(
    geometry: shapely.Geometry,
) -> collections.abc.Iterator[shapely.LinearRing]:
    """Visit nonempty polygon boundaries in the measurement's recursive order.

    Args:
        geometry: The polygon set whose boundaries will be measured.

    Yields:
        Each polygon's exterior followed by its holes, preserving collection order.
    """
    if isinstance(geometry, shapely.Polygon):
        if not geometry.is_empty:
            yield geometry.exterior
            yield from geometry.interiors
    elif isinstance(geometry, shapely.MultiPolygon | shapely.GeometryCollection):
        for part in geometry.geoms:
            yield from polygon_rings(part)


def area_from_ring_areas(
    geometry: shapely.Geometry,
    measurements: collections.abc.Iterator[pint.Quantity[float]],
) -> pint.Quantity[float]:
    """Reduce boundary measurements with the geometry's original nesting.

    Args:
        geometry: The polygon set defining signs and collection addition order.
        measurements: Signed ring areas in exterior-then-hole traversal order.

    Returns:
        Polygon surface area with independent ring winding and zero line area.
    """
    if isinstance(geometry, shapely.Polygon):
        if geometry.is_empty:
            return units.Quantity(0.0, SQUARE_METERS)
        return (
            abs(next(measurements))
            - math.fsum(
                abs(next(measurements)).m_as(SQUARE_METERS)
                for _interior in geometry.interiors
            )
            * SQUARE_METERS
        )
    if isinstance(geometry, shapely.MultiPolygon | shapely.GeometryCollection):
        return units.Quantity(
            math.fsum(
                area_from_ring_areas(part, measurements).m_as(SQUARE_METERS)
                for part in geometry.geoms
            ),
            SQUARE_METERS,
        )
    return units.Quantity(0.0, SQUARE_METERS)


def ring_area(ring: shapely.LinearRing) -> pint.Quantity[float]:
    """Integrate an oriented boundary using a local reference latitude.

    A ring-local reference latitude keeps intermediate values small for narrow
    slivers. Summation converts the edge contributions to native square meters.

    Args:
        ring: A closed polygon boundary in longitude and latitude degrees.

    Returns:
        Signed surface area in square meters, positive counterclockwise.
    """
    if ring.is_empty:
        return units.Quantity(0.0, SQUARE_METERS)
    return ring_areas((ring,))[0]


def ring_areas(
    rings: collections.abc.Sequence[shapely.LinearRing],
) -> pint.Quantity[Coordinates]:
    """Batch polygon boundaries while retaining every ring's summation order.

    Each ring retains its own reference latitude. Quadrature temporaries hold at
    most ``MAXIMUM_INTEGRATION_BATCH_PIECES`` intervals, including when one large
    boundary spans multiple batches. Each complete ring is summed once with fsum.

    Args:
        rings: Nonempty closed boundaries in the required measurement order.

    Returns:
        Signed square-meter measurements aligned with the input boundaries.
    """
    if not rings:
        return units.Quantity(np.empty(0), SQUARE_METERS)
    coordinates, coordinate_ring_indices = shapely.get_coordinates(
        rings,
        return_index=True,
    )
    lengths = np.bincount(coordinate_ring_indices)
    ring_starts = np.r_[0, np.cumsum(lengths)[:-1]]
    first_coordinate = np.zeros(len(coordinates), dtype=bool)
    last_coordinate = np.zeros(len(coordinates), dtype=bool)
    first_coordinate[ring_starts] = True
    last_coordinate[np.cumsum(lengths) - 1] = True
    latitude_references = units.Quantity(
        (
            np.minimum.reduceat(coordinates[:, 1], ring_starts)
            + np.maximum.reduceat(coordinates[:, 1], ring_starts)
        )
        / 2,
        DEGREES,
    )
    contributions, edge_ring_indices = ring_edge_contributions(
        coordinates[~last_coordinate],
        coordinates[~first_coordinate],
        coordinate_ring_indices[~last_coordinate],
        latitude_references,
    )
    stops = np.cumsum(np.bincount(edge_ring_indices, minlength=len(rings)))
    starts = np.r_[0, stops[:-1]]
    return units.Quantity(
        np.fromiter(
            (
                math.fsum(contributions.magnitude[start:stop])
                for start, stop in zip(starts, stops, strict=True)
            ),
            dtype=float,
        ),
        SQUARE_METERS,
    )


def ring_edge_contributions(
    start: Coordinates,
    end: Coordinates,
    edge_ring_indices: npt.NDArray[np.int64],
    latitude_references: pint.Quantity[Coordinates],
) -> tuple[pint.Quantity[Coordinates], npt.NDArray[np.int64]]:
    """Integrate raw-coordinate edges without creating geometry vertices.

    Args:
        start: Original edge-start coordinates in longitude/latitude degrees.
        end: Original edge-end coordinates in longitude/latitude degrees.
        edge_ring_indices: The owning boundary for each edge.
        latitude_references: One numerical reference latitude per boundary.

    Returns:
        Signed square-meter contributions and their aligned boundary identities.
    """
    nonvertical = end[:, 0] - start[:, 0] != 0
    longitude_difference = units.Quantity(
        end[nonvertical, 0] - start[nonvertical, 0],
        DEGREES,
    )
    latitude_difference = units.Quantity(
        end[nonvertical, 1] - start[nonvertical, 1],
        DEGREES,
    )
    starting_latitudes = units.Quantity(start[nonvertical, 1], DEGREES)
    edge_ring_indices = edge_ring_indices[nonvertical]
    longitude_difference, latitude_difference, starting_latitudes, edge_ring_indices = (
        subdivide_edges(
            longitude_difference,
            latitude_difference,
            starting_latitudes,
            edge_ring_indices,
        )
    )
    references = units.Quantity(
        latitude_references.magnitude[edge_ring_indices],
        latitude_references.units,
    )
    # Form the complete midpoint offset in degrees before converting to radians.
    latitude_offsets = units.Quantity(
        (
            starting_latitudes.magnitude
            - references.m_as(DEGREES)
            + latitude_difference.magnitude / 2
        )
        * DEGREE_TO_RADIAN,
        RADIANS,
    )
    return integration_contributions(
        longitude_difference,
        latitude_offsets,
        units.Quantity(latitude_difference.magnitude * DEGREE_TO_RADIAN / 2, RADIANS),
        references=references,
        latitude_references=latitude_references,
        edge_ring_indices=edge_ring_indices,
    ), edge_ring_indices


def subdivide_edges(
    longitude_difference: pint.Quantity[Coordinates],
    latitude_difference: pint.Quantity[Coordinates],
    starting_latitudes: pint.Quantity[Coordinates],
    edge_ring_indices: npt.NDArray[np.int64],
) -> tuple[
    pint.Quantity[Coordinates],
    pint.Quantity[Coordinates],
    pint.Quantity[Coordinates],
    npt.NDArray[np.int64],
]:
    """Limit numerical latitude intervals to one degree while preserving edge order.

    Args:
        longitude_difference: Oriented longitude width of each edge.
        latitude_difference: Oriented latitude width of each edge.
        starting_latitudes: The starting latitude of each edge.
        edge_ring_indices: The boundary owning each edge.

    Returns:
        Longitude widths, latitude widths, starting latitudes, and boundary identities
        aligned with the subdivision intervals.
    """
    latitude_widths = abs(latitude_difference.to(DEGREES))
    if np.any(latitude_widths.magnitude > 1):
        piece_counts = np.maximum(1, np.ceil(latitude_widths.magnitude).astype(int))
        edge_indices = np.repeat(np.arange(len(piece_counts)), piece_counts)
        piece_starts = np.cumsum(piece_counts) - piece_counts
        piece_numbers = np.arange(len(edge_indices)) - piece_starts[edge_indices]
        longitude_difference = units.Quantity(
            longitude_difference.magnitude[edge_indices] / piece_counts[edge_indices],
            longitude_difference.units,
        )
        latitude_steps = units.Quantity(
            latitude_difference.magnitude[edge_indices] / piece_counts[edge_indices],
            latitude_difference.units,
        )
        latitude_shifts = units.Quantity(
            piece_numbers * latitude_steps.magnitude,
            latitude_steps.units,
        )
        starting_latitudes = units.Quantity(
            starting_latitudes.magnitude[edge_indices]
            + latitude_shifts.m_as(starting_latitudes.units),
            starting_latitudes.units,
        )
        latitude_difference = latitude_steps
        edge_ring_indices = edge_ring_indices[edge_indices]
    return (
        longitude_difference,
        latitude_difference,
        starting_latitudes,
        edge_ring_indices,
    )


def integration_contributions(
    longitude_difference: pint.Quantity[Coordinates],
    latitude_offsets: pint.Quantity[Coordinates],
    half_latitude_difference: pint.Quantity[Coordinates],
    *,
    references: pint.Quantity[Coordinates],
    latitude_references: pint.Quantity[Coordinates],
    edge_ring_indices: npt.NDArray[np.int64],
) -> pint.Quantity[Coordinates]:
    """Bound quadrature temporaries without rounding intermediate ring sums.

    Args:
        longitude_difference: Oriented longitude width of each integration piece.
        latitude_offsets: Piece midpoint latitudes relative to their ring references.
        half_latitude_difference: Half the oriented latitude width of each piece.
        references: The reference latitude aligned with each piece.
        latitude_references: One original reference latitude per boundary.
        edge_ring_indices: The boundary owning each piece.

    Returns:
        Oriented surface-integral contributions in original edge and piece order.
    """
    reference_sines = [math.sin(value) for value in latitude_references.m_as(RADIANS)]
    reference_denominators = np.fromiter(
        (1 - ECCENTRICITY_SQUARED * value**2 for value in reference_sines),
        dtype=float,
    )
    reference_sine_array = np.asarray(reference_sines)
    contributions = units.Quantity(
        np.empty(len(longitude_difference)),
        SQUARE_METERS,
    )
    offset_unit = latitude_offsets.units
    same_units = offset_unit == half_latitude_difference.units
    for start_index in range(0, len(contributions), MAXIMUM_INTEGRATION_BATCH_PIECES):
        selected = slice(start_index, start_index + MAXIMUM_INTEGRATION_BATCH_PIECES)
        selected_ring_indices = edge_ring_indices[selected]
        quadrature_offsets = (
            units.Quantity(
                latitude_offsets.magnitude[selected, None]
                + half_latitude_difference.magnitude[selected, None]
                * GAUSSIAN_NODES[None, :],
                offset_unit,
            )
            if same_units
            else latitude_offsets[selected, None]
            + half_latitude_difference[selected, None] * GAUSSIAN_NODES[None, :]
        )
        primitive_values = primitive_difference_with_reference_values(
            quadrature_offsets,
            references[selected, None].to(RADIANS),
            reference_sine_array[selected_ring_indices, None],
            reference_denominators[selected_ring_indices, None],
        )
        contributions.magnitude[selected] = -longitude_difference[selected].m_as(
            RADIANS,
        ) * np.sum(primitive_values.magnitude * GAUSSIAN_MEAN_WEIGHTS, axis=1)
    return contributions


def latitude_primitive_difference(
    latitude_offsets: pint.Quantity[Coordinates],
    latitude_reference: pint.Quantity[float],
) -> pint.Quantity[Coordinates]:
    """Evaluate the surface primitive relative to a latitude without cancellation.

    Args:
        latitude_offsets: Quadrature positions relative to the reference latitude.
        latitude_reference: The numerical reference latitude.

    Returns:
        Surface primitive differences as square-meter quantities.
    """
    reference_sine = math.sin(latitude_reference.m_as("radians"))
    return primitive_difference_with_reference_values(
        latitude_offsets,
        latitude_reference,
        reference_sine,
        1 - ECCENTRICITY_SQUARED * reference_sine**2,
    )


def primitive_difference_with_reference_values(
    latitude_offsets: pint.Quantity[Coordinates],
    latitude_reference: pint.Quantity[float] | pint.Quantity[Coordinates],
    reference_sine: float | Coordinates,
    reference_denominator: float | Coordinates,
) -> pint.Quantity[Coordinates]:
    """Share the stable primitive between scalar and batched reference latitudes.

    Args:
        latitude_offsets: Quadrature positions relative to the reference latitude.
        latitude_reference: The numerical reference latitude.
        reference_sine: Scalar-calculated sine of each reference latitude.
        reference_denominator: The scalar reference's ellipsoid denominator.

    Returns:
        Surface primitive differences as square-meter quantities.
    """
    sine_difference = (
        2
        * np.cos((latitude_reference + latitude_offsets / 2).m_as("radians"))
        * np.sin((latitude_offsets / 2).m_as("radians"))
    )
    sine = reference_sine + sine_difference
    product = ECCENTRICITY_SQUARED * sine * reference_sine
    rational_difference = (
        sine_difference
        * (1 + product)
        / ((1 - ECCENTRICITY_SQUARED * sine**2) * reference_denominator)
    )
    logarithmic_difference = (
        np.arctanh(ECCENTRICITY * sine_difference / (1 - product)) / ECCENTRICITY
    )
    return units.Quantity(
        SURFACE_SCALE.magnitude * (rational_difference + logarithmic_difference),
        SQUARE_METERS,
    )
