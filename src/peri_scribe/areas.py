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

import peri_scribe.geo.parsing
import peri_scribe.units
from peri_scribe.units import units


if TYPE_CHECKING:
    import pandas as pd
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


PERIMETER_AREA_COLUMN = "area_acres"
POINT_AREA_COLUMN = "incident_size"


def _row_number(row: pd.Series | None, column: str) -> float | None:
    """Return *row*'s numeric value in *column*, or None when it is missing.

    Args:
        row: A history row, or None.
        column: The column to read.

    Returns:
        The column's numeric value, or None when the row or value is missing.
    """
    if row is None or column not in row.index:
        return None
    value = row[column]
    if peri_scribe.geo.parsing.is_missing(value):
        return None
    return peri_scribe.geo.parsing.numeric_value(value)


def presented_area_for_latest(
    perimeter_row: pd.Series | None,
    point_row: pd.Series | None,
) -> pint.Quantity[float] | None:
    """Return the area presented for a fire's latest perimeter, else its point.

    The latest perimeter supplies the reported acreage, falling back to the latest
    point's incident size when the perimeter has none. When the perimeter's geometry
    measures significantly larger than the reported acreage, the measured area is
    presented instead, matching :func:`presented_area`. This is the single source of
    truth for the area a fire displays, scores, and is gated on.

    Args:
        perimeter_row: The fire's latest perimeter history row, or None.
        point_row: The fire's latest point history row, or None.

    Returns:
        The presented area, or None when neither row reports one.
    """
    reported = _row_number(perimeter_row, PERIMETER_AREA_COLUMN)
    if reported is None:
        reported = _row_number(point_row, POINT_AREA_COLUMN)
    geometry = (
        getattr(perimeter_row, "geometry", None) if perimeter_row is not None else None
    )
    if reported is not None and geometry is not None and not geometry.is_empty:
        return presented_area(
            reported * units.acres,
            peri_scribe.units.area(geometry),
        )
    if reported is not None:
        return reported * units.acres
    return None
