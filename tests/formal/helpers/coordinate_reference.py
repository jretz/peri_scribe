"""Compare reference selection using real CRS metadata and exact binary coordinates."""

import functools
import itertools
import math

import arcgis_access.spatial_reference


MATCHING = 2
type Bounds = tuple[float, float, float, float]
EXTENTS: dict[str, Bounds | None] = {
    "missing": None,
    "california": (-123.0, -120.0, 35.0, 39.0),
    "alaska": (-152.0, -149.0, 60.0, 63.0),
    "hawaii": (-158.0, -155.0, 19.0, 22.0),
    "puerto-rico": (-67.0, -65.0, 17.0, 19.0),
    "outside-us": (20.0, 21.0, 30.0, 31.0),
    "east-antimeridian": (179.0, 180.0, 50.0, 51.0),
    "west-antimeridian": (-180.0, -179.0, 50.0, 51.0),
    "world": (-180.0, 180.0, -90.0, 90.0),
    "origin": (0.0, 0.0, 0.0, 0.0),
    "projected": (-14000000.0, -13000000.0, 4000000.0, 5000000.0),
    "cross-origin": (-200000.0, 200000.0, -200000.0, 200000.0),
}


def integers(values: tuple[float, ...]) -> str:
    """Use one positive binary scale without rounding any compared input.

    Args:
        values: Finite coordinates or domain limits.

    Returns:
        Integers with the exact same ordering and signs as the supplied numbers.
    """
    ratios = [float(value).as_integer_ratio() for value in values]
    denominator = max((pair[1] for pair in ratios), default=1)
    return " ".join(
        str(numerator * (denominator // scale)) for numerator, scale in ratios
    )


@functools.cache
def metadata(identifier: int) -> tuple[float, ...]:
    """Expose provider-independent CRS facts to the compiled candidate policy.

    Args:
        identifier: One reported EPSG or ESRI code.

    Returns:
        Availability, geographic status, domain bands, and optional area bounds.
    """
    domain = arcgis_access.spatial_reference.spatial_reference_domain(identifier)
    if domain is None:
        return (0.0,) * 11
    area = domain.crs.area_of_use
    return (
        1.0,
        float(domain.crs.is_geographic),
        *domain.bands,
        float(area is not None),
        *((area.west, area.east, area.south, area.north) if area else (0.0,) * 4),
    )


def command(
    identifiers: tuple[int, ...],
    bounds: tuple[float, float, float, float] | None,
) -> str:
    """Scale numerical facts exactly while preserving identity and Boolean meaning.

    Args:
        identifiers: Reported reference candidates in any order.
        bounds: Observed extent, or no usable geometry.

    Returns:
        A selection request including exact common-scale numerical metadata.
    """
    records = [metadata(identifier) for identifier in identifiers]
    values = (*(bounds or ()), *(value for record in records for value in record))
    scaled = [int(value) for value in integers(values).split()]
    count = 4 if bounds is not None else 0
    parts = ["selection", " ".join(map(str, scaled[:count]))]
    for index, identifier in enumerate(identifiers):
        fields = scaled[count + index * 11 : count + (index + 1) * 11]
        parts.append(" ".join(map(str, (identifier, *fields))))
    return "|".join(parts)


def axis_cases() -> list[tuple[float, float, float, float]]:
    """Cross zero, exact limits, and adjacent representable floating-point values.

    Returns:
        Ordered finite intervals and nonnegative magnitude bands.
    """
    points = (-200.0, -180.0, -90.0, -1.0, -0.0, 0.5, 1.0, 90.0, 180.0, 200.0)
    bounds = [(low, high) for low in points for high in points if low <= high]
    bands = ((0.0, 90.0), (0.0, 180.0), (1.0, 200.0), (90.0, 180.0))
    result = [
        (low, high, lower, upper) for low, high in bounds for lower, upper in bands
    ]
    for lower, upper in bands:
        for value in (lower, upper, -lower, -upper):
            for direction in (-math.inf, math.inf):
                adjacent = math.nextafter(value, direction)
                result.append((adjacent, adjacent, lower, upper))
    return result


def selection_cases(
    bounds: Bounds | None,
) -> list[tuple[tuple[int, ...], Bounds | None]]:
    """Exercise complete selection across geographic, projected, and invalid references.

    Args:
        bounds: One independently checked extent from the geographic coverage matrix.

    Returns:
        Every candidate subset paired with the selected extent.
    """
    candidates = (4326, 4269, 4267, 3857, 3310, 3338, 5703, 999999)
    return [
        (selection, bounds)
        for length in range(4)
        for selection in itertools.combinations(candidates, length)
    ]
