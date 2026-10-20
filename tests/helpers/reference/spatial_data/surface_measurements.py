"""Independent high-precision Fourier integration of straight coordinate boundaries.

The reference expands the ellipsoid's surface primitive in powers of eccentricity,
then integrates each odd sine power as a finite Fourier sum. It shares neither the
production primitive-difference formula nor its Gaussian quadrature.
"""

from __future__ import annotations

import decimal
import itertools
import math

import shapely

from measurement_units import units


PI = decimal.Decimal(
    "3.141592653589793238462643383279502884197169399375105820974944592307816406286",
)


def sine(value: decimal.Decimal) -> decimal.Decimal:
    """Evaluate a radian argument with a convergent high-precision Taylor series.

    Args:
        value: A dimensionless angle in radians.

    Returns:
        The angle's sine at the active Decimal precision.
    """
    value %= 2 * PI
    if value > PI:
        value -= 2 * PI
    term = value
    total = value
    index = 1
    while True:
        term *= -(value * value) / ((2 * index) * (2 * index + 1))
        updated = total + term
        if updated == total:
            return total
        total = updated
        index += 1


def integrated_sine_power(
    power: int,
    midpoint: decimal.Decimal,
    half_difference: decimal.Decimal,
) -> decimal.Decimal:
    """Average an odd power of sine over one straight latitude interval.

    Args:
        power: The nonnegative index representing sine power ``2 * power + 1``.
        midpoint: The interval's middle latitude in radians.
        half_difference: Half the oriented latitude interval in radians.

    Returns:
        The average of that sine power along the interval.
    """
    odd_power = 2 * power + 1
    result = decimal.Decimal(0)
    for index in range(power + 1):
        frequency = odd_power - 2 * index
        angle = frequency * half_difference
        sinc = sine(angle) / angle if angle else decimal.Decimal(1)
        result += (
            (-1) ** index
            * math.comb(odd_power, index)
            * sine(frequency * midpoint)
            * sinc
        )
    return result * decimal.Decimal((-1) ** power) / (2 ** (2 * power))


def ring_area(ring: shapely.LinearRing) -> float:
    """Measure a boundary at 65-digit precision with a bounded eccentricity tail.

    Twenty terms leave less than 1e-27 square meters per radian of longitude in
    the omitted WGS84 primitive series. The final conversion rounds to binary64.

    Args:
        ring: A closed ring of longitude/latitude degree coordinates.

    Returns:
        Signed boundary area in native square meters.
    """
    with decimal.localcontext() as context:
        context.prec = 65
        major_radius = decimal.Decimal(6_378_137) * units.meters
        flattening = 1 / decimal.Decimal("298.257223563")
        eccentricity_squared = flattening * (2 - flattening)
        degrees_to_radians = PI / 180
        coordinates = shapely.get_coordinates(ring)
        total = decimal.Decimal(0)
        for start, end in itertools.pairwise(coordinates):
            longitude_difference = (
                decimal.Decimal(float(end[0])) - decimal.Decimal(float(start[0]))
            ) * degrees_to_radians
            if not longitude_difference:
                continue
            start_latitude = decimal.Decimal(float(start[1])) * degrees_to_radians
            end_latitude = decimal.Decimal(float(end[1])) * degrees_to_radians
            midpoint = (start_latitude + end_latitude) / 2
            half_difference = (end_latitude - start_latitude) / 2
            primitive = sum(
                (
                    (power + 1)
                    * eccentricity_squared**power
                    / (2 * power + 1)
                    * integrated_sine_power(power, midpoint, half_difference)
                )
                for power in range(20)
            )
            total -= longitude_difference * primitive
        result = total * major_radius**2 * (1 - eccentricity_squared)
        return float(result.m_as("meters ** 2"))


def area(geometry: shapely.Geometry) -> float:
    """Measure polygon leaves using the independent high-precision boundary rule.

    Args:
        geometry: A polygon set with straight longitude/latitude edges.

    Returns:
        Polygon surface area in native square meters.
    """
    if isinstance(geometry, shapely.Polygon):
        return abs(ring_area(geometry.exterior)) - math.fsum(
            abs(ring_area(interior)) for interior in geometry.interiors
        )
    if isinstance(geometry, shapely.MultiPolygon | shapely.GeometryCollection):
        return math.fsum(area(part) for part in geometry.geoms)
    return 0.0
