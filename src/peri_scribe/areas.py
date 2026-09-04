"""Choosing the acreage presented when reported and calculated sizes disagree.

A mapped perimeter carries the acreage its source reported (usually the polygon's GIS
acres field) and the area peri_scribe measures from the same polygon's geometry. The two
normally agree within a rounding step, so the reported acreage is what users see. When
the measured area is significantly larger than the reported acreage, the reported figure
is stale or understated — the polygon the source published is bigger than its field
admits — and the measured area is presented instead, so every user-facing size shows the
fire the map actually draws.
"""

from __future__ import annotations


# A geometry-measured area at least this many times the reported acreage is treated as
# significantly larger. Reported polygon acreages track their polygons within a few
# percent, so a multiple this large means the reported figure did not keep up with the
# geometry rather than a difference in rounding.
SIGNIFICANTLY_LARGER_AREA_RATIO = 1.25


def presented_area_in_acres(
    reported_in_acres: float | None,
    calculated_in_acres: float | None,
) -> float | None:
    """Return the acreage to present when reported and calculated sizes disagree.

    The calculated area is presented when it is at least
    :data:`SIGNIFICANTLY_LARGER_AREA_RATIO` times the reported area, or when the
    reported area is zero or negative and the calculated area is positive. A reported
    figure that is missing leaves the result missing, and a calculated figure that is
    missing leaves the reported figure in place, so the rule never invents an area the
    data does not support.

    Args:
        reported_in_acres: The acreage the source reported, or None.
        calculated_in_acres: The area measured from the mapped geometry, or None.

    Returns:
        The calculated area when it is significantly larger than the reported area, and
        the reported area otherwise.

    Examples:
        >>> presented_area_in_acres(1100.0, 2939.0)
        2939.0

        >>> presented_area_in_acres(1100.0, 1110.0)
        1100.0

        >>> presented_area_in_acres(None, 2939.0) is None
        True

        >>> presented_area_in_acres(1100.0, None)
        1100.0

        >>> presented_area_in_acres(0.0, 2939.0)
        2939.0
    """
    if reported_in_acres is None or calculated_in_acres is None:
        return reported_in_acres
    if reported_in_acres <= 0.0:
        return calculated_in_acres if calculated_in_acres > 0.0 else reported_in_acres
    if calculated_in_acres >= reported_in_acres * SIGNIFICANTLY_LARGER_AREA_RATIO:
        return calculated_in_acres
    return reported_in_acres
