"""Choosing the area presented when reported and calculated sizes disagree.

A mapped perimeter carries the acreage its source reported (usually the polygon's GIS
acres field) and the area peri_scribe measures from the same polygon's geometry. The two
normally agree within a rounding step, so the reported acreage is what users see. When
the measured area is significantly larger than the reported acreage, the reported figure
is stale or understated — the polygon the source published is bigger than its field
admits — and the measured area is presented instead, so every user-facing size shows the
fire the map actually draws.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    import pint


# A geometry-measured area at least this many times the reported acreage is treated as
# significantly larger. Reported polygon acreages track their polygons within a few
# percent, so a multiple this large means the reported figure did not keep up with the
# geometry rather than a difference in rounding.
SIGNIFICANTLY_LARGER_AREA_RATIO = 1.25


def presented_area(
    reported: pint.Quantity[float] | None,
    calculated: pint.Quantity[float] | None,
) -> pint.Quantity[float] | None:
    """Return the area to present when reported and calculated sizes disagree.

    The calculated area is presented when it is at least
    :data:`SIGNIFICANTLY_LARGER_AREA_RATIO` times the reported area, or when the
    reported area is zero or negative and the calculated area is positive. A reported
    figure that is missing leaves the result missing, and a calculated figure that is
    missing leaves the reported figure in place, so the rule never invents an area the
    data does not support.

    Args:
        reported: The area the source reported, or None.
        calculated: The area measured from the mapped geometry, or None.

    Returns:
        The calculated area when it is significantly larger than the reported area, and
        the reported area otherwise.

    Examples:
        >>> from peri_scribe.units import units
        >>> presented_area(1100.0 * units.acres, 2939.0 * units.acres)
        <Quantity(2939.0, 'acre')>

        >>> presented_area(1100.0 * units.acres, 1110.0 * units.acres)
        <Quantity(1100.0, 'acre')>

        >>> presented_area(None, 2939.0 * units.acres) is None
        True

        >>> presented_area(1100.0 * units.acres, None)
        <Quantity(1100.0, 'acre')>

        >>> presented_area(0.0 * units.acres, 2939.0 * units.acres)
        <Quantity(2939.0, 'acre')>
    """
    if reported is None or calculated is None:
        return reported
    if reported <= 0.0:
        if calculated > 0.0:
            return calculated
        return reported
    if calculated >= reported * SIGNIFICANTLY_LARGER_AREA_RATIO:
        return calculated
    return reported
