"""Building the human-readable description shown in each fire placemark's KML balloon.

A fire's geography is drawn as several placemarks: its point location, its latest filled
perimeter, a few outline perimeters, and its growth rings. Every one of those placemarks
shows the same balloon describing the fire's latest state, so the person reading the map
sees the fire's current size, cost, and timing regardless of which shape they click.

The description is formatted for people rather than for a database: numbers carry
thousands separators and units, and timestamps are shown in America/Los_Angeles time
with an explicit PDT or PST marker.
"""

from __future__ import annotations

import dataclasses
import datetime
import html
import math

import peri_scribe.perimeters.progression


# Areas at or above this many acres are shown as whole acres; smaller areas keep one or
# two decimal places so small fires do not read as zero.
WHOLE_ACRE_THRESHOLD = 100.0

# A fire at or above this containment percentage is fully contained and needs no
# contained-length annotation.
FULL_CONTAINMENT_IN_PERCENT = 100.0

# Perimeter lengths keep at most this many digits after the decimal point and at most
# this many significant digits, so a large fire's perimeter keeps its scale without
# implying more precision than the mapping supports.
MAX_PERIMETER_DECIMAL_PLACES = 1
MAX_PERIMETER_SIGNIFICANT_DIGITS = 3

# At one decimal place, lengths at or above this carry more than three significant
# digits and are re-rounded to three.
PERIMETER_SIGNIFICANT_DIGIT_THRESHOLD = 100.0

# Rows alternate between white and this light background so the eye can follow each
# label across the balloon.
ALT_ROW_BACKGROUND_COLOR = "#EEF3F8"

# The balloon's body text is slightly larger than Google Earth's default, so the
# description reads easily at a glance.
BODY_FONT_SIZE_IN_PIXELS = 14


def format_number(value: float | None, decimal_places: int = 0) -> str | None:
    """Format *value* with thousands separators and *decimal_places* decimals.

    Args:
        value: The number to format, or None.
        decimal_places: The number of decimal places to keep, or 0 for a whole
            number.

    Returns:
        The formatted number, or None when *value* is None.

    Examples:
        >>> format_number(1234.5, 1)
        '1,234.5'

        >>> format_number(None) is None
        True
    """
    if value is None:
        return None
    if decimal_places <= 0:
        return f"{round(value):,}"
    return f"{value:,.{decimal_places}f}".rstrip("0").rstrip(".")


def format_in_acres(value: float | None) -> str | None:
    """Format an area in acres with a unit and size-appropriate precision.

    Args:
        value: The area in acres, or None.

    Returns:
        The formatted area, like ``102,003 acres`` or ``6.5 acres``, or None.

    Examples:
        >>> format_in_acres(6.5)
        '6.5 acres'
    """
    if value is None:
        return None
    if abs(value) >= WHOLE_ACRE_THRESHOLD:
        number = format_number(value, 0)
    elif abs(value) >= 1:
        number = format_number(value, 1)
    else:
        number = format_number(value, 2)
    return f"{number} acres"


def format_in_percent(value: float | None) -> str | None:
    """Format a containment percentage with a percent sign.

    Args:
        value: The percentage, or None.

    Returns:
        The formatted percentage, like ``77%``, or None.

    Examples:
        >>> format_in_percent(77)
        '77%'

        >>> format_in_percent(0.5)
        '0.5%'
    """
    if value is None:
        return None
    decimal_places = 1 if 0 < abs(value) < 1 else 0
    return f"{format_number(value, decimal_places)}%"


def round_to_significant_digits(value: float, digits: int) -> float:
    """Return *value* rounded to *digits* significant digits.

    Args:
        value: The value to round.
        digits: The number of significant digits to keep.

    Returns:
        The rounded value.

    Examples:
        >>> round_to_significant_digits(1234.5, 3)
        1230.0

        >>> round_to_significant_digits(1205.6, 3)
        1210.0
    """
    if math.isclose(value, 0.0):
        return 0.0
    exponent = math.floor(math.log10(abs(value)))
    return round(value, digits - 1 - exponent)


def format_perimeter_length(value: float | None) -> str | None:
    """Format a perimeter length in miles, with a capped precision.

    The length is rounded to at most one decimal place and to at most three significant
    digits: ``0.1499`` becomes ``0.1``, ``3.1415`` becomes ``3.1``, ``123.6`` becomes
    ``124``, and ``5678.123`` becomes ``5,680``.

    Args:
        value: The length in miles, or None.

    Returns:
        The formatted length, or None when *value* is None.

    Examples:
        >>> format_perimeter_length(3.1415)
        '3.1'

        >>> format_perimeter_length(5678.123)
        '5,680'
    """
    if value is None:
        return None
    rounded = round(value, MAX_PERIMETER_DECIMAL_PLACES)
    if abs(rounded) >= PERIMETER_SIGNIFICANT_DIGIT_THRESHOLD:
        rounded = round_to_significant_digits(
            rounded,
            MAX_PERIMETER_SIGNIFICANT_DIGITS,
        )
    return format_number(rounded, MAX_PERIMETER_DECIMAL_PLACES)


def format_in_miles(value: float | None) -> str | None:
    """Format a length in miles with a unit.

    Args:
        value: The length in miles, or None.

    Returns:
        The formatted length, like ``33.1 miles``, or None.

    Examples:
        >>> format_in_miles(33.14)
        '33.1 miles'
    """
    if value is None:
        return None
    return f"{format_perimeter_length(value)} miles"


def format_containment(
    percent_contained: float | None,
    exterior_perimeter_in_miles: float | None,
) -> str | None:
    """Format a containment percentage, annotated with its contained length.

    When the exterior perimeter length is known the percentage is followed by the length
    it represents: ``68% (22.5 of 33.1 miles)``, where the last number is the exterior
    perimeter length and the first number in parentheses is that percentage of it. A
    fire that is fully contained (100%) shows only the percentage, as does a fire
    without a perimeter length; without a percentage there is nothing to show.

    Args:
        percent_contained: The containment percentage, or None.
        exterior_perimeter_in_miles: The exterior perimeter length in miles, or
            None.

    Returns:
        The formatted containment, or None.

    Examples:
        >>> format_containment(68, 33.1)
        '68% (22.5 of 33.1 miles)'
    """
    if percent_contained is None:
        return None
    percent_text = format_in_percent(percent_contained)
    if exterior_perimeter_in_miles is None:
        return percent_text
    if percent_contained >= FULL_CONTAINMENT_IN_PERCENT:
        return percent_text
    contained_in_miles = percent_contained / 100.0 * exterior_perimeter_in_miles
    return (
        f"{percent_text} "
        f"({format_perimeter_length(contained_in_miles)} of "
        f"{format_perimeter_length(exterior_perimeter_in_miles)} miles)"
    )


def format_cost_in_dollars(value: float | None) -> str | None:
    """Format a cost in whole dollars with a dollar sign.

    Args:
        value: The cost in dollars, or None.

    Returns:
        The formatted cost, like ``$104,600,000``, or None.

    Examples:
        >>> format_cost_in_dollars(104600000)
        '$104,600,000'
    """
    if value is None:
        return None
    return f"${format_number(value, 0)}"


def format_personnel_count(value: float | None) -> str | None:
    """Format a personnel count as a whole number with thousands separators.

    Args:
        value: The number of personnel, or None.

    Returns:
        The formatted count, like ``1,234``, or None.

    Examples:
        >>> format_personnel_count(1234)
        '1,234'
    """
    if value is None:
        return None
    return format_number(value, 0)


def format_pacific_time(value: datetime.datetime | None) -> str | None:
    """Format *value* in America/Los_Angeles time with its PDT or PST marker.

    Every fire in a year's output is observed in the same year, so the year is left off
    the timestamp.

    Args:
        value: An aware datetime, or None.

    Returns:
        The formatted timestamp, like ``08/02 22:30 PDT``, or None.

    Examples:
        >>> format_pacific_time(
        ...     datetime.datetime(2025, 8, 2, 5, 30, tzinfo=datetime.UTC),
        ... )
        '08/01 22:30 PDT'
    """
    if value is None:
        return None
    pacific = value.astimezone(peri_scribe.perimeters.progression.CALIFORNIA_TIME_ZONE)
    zone = pacific.tzname() or ""
    return f"{pacific:%m/%d %H:%M} {zone}"


@dataclasses.dataclass(frozen=True, kw_only=True)
class FireDescription:
    """The latest state of a fire, ready to format into a balloon."""

    identifier: str | None = None
    source: str | None = None
    mission: str | None = None
    area_in_acres: float | None = None
    exterior_perimeter_in_miles: float | None = None
    percent_contained: float | None = None
    estimated_cost_to_date_in_dollars: float | None = None
    estimated_final_cost_in_dollars: float | None = None
    total_personnel: float | None = None
    protecting_unit: str | None = None
    discovery_time: datetime.datetime | None = None
    observation_time: datetime.datetime | None = None
    initial_response_time: datetime.datetime | None = None
    incident_type: str | None = None
    incident_complexity: str | None = None
    fuel_model: str | None = None
    fire_behavior: str | None = None
    landowner_category: str | None = None
    of_note: str | None = None


def escape_text(value: str) -> str:
    """Escape *value* for safe display inside the balloon's HTML.

    Args:
        value: The text to escape.

    Returns:
        The text with HTML-significant characters escaped.
    """
    return html.escape(value, quote=False)


def description_rows(
    description: FireDescription,
) -> list[tuple[str, str]]:
    """Return the label/value rows shown in *description*'s balloon.

    Every row is always present; a row whose value is missing keeps its label and shows
    two hyphens, so the reader can see at a glance which facts the fire lacks rather
    than guessing from omitted rows.

    Args:
        description: The fire's latest state.

    Returns:
        The display rows, in reading order.
    """
    rows: list[tuple[str, str]] = []
    candidates: list[tuple[str, str | None]] = [
        ("Area", format_in_acres(description.area_in_acres)),
        (
            "Exterior perimeter",
            format_in_miles(description.exterior_perimeter_in_miles),
        ),
        (
            "Containment",
            format_containment(
                description.percent_contained,
                description.exterior_perimeter_in_miles,
            ),
        ),
        (
            "Cost to date",
            format_cost_in_dollars(description.estimated_cost_to_date_in_dollars),
        ),
        (
            "Estimated final cost",
            format_cost_in_dollars(description.estimated_final_cost_in_dollars),
        ),
        ("Personnel", format_personnel_count(description.total_personnel)),
        ("Source", description.source),
        ("Identifier", description.identifier),
        ("Mission", description.mission),
        ("Protecting unit", description.protecting_unit),
        ("Discovery", format_pacific_time(description.discovery_time)),
        ("Last update", format_pacific_time(description.observation_time)),
        ("Initial response", format_pacific_time(description.initial_response_time)),
        ("Incident type", description.incident_type),
        ("Incident complexity", description.incident_complexity),
        ("Fuel model", description.fuel_model),
        ("Fire behavior", description.fire_behavior),
        ("Landowner category", description.landowner_category),
        ("Of note", description.of_note),
    ]
    for label, value in candidates:
        rows.append((label, "--" if value is None else value))
    return rows


def description_html(
    description: FireDescription,
    image_filenames: tuple[str, ...] = (),
) -> str:
    """Return *description* as the HTML KML balloon text.

    The text is wrapped in a CDATA section so the HTML tags it contains survive as
    markup rather than being read as KML text. Each of *image_filenames* is shown below
    the table as an image whose source is a file stored beside the KML in the KMZ
    archive.

    Args:
        description: The fire's latest state.
        image_filenames: The relative filename of each plot image to show, in
            display order.

    Returns:
        The balloon's KML description text.
    """
    body_style = f' style="font-size:{BODY_FONT_SIZE_IN_PIXELS}px;"'
    parts = [
        f'<table cellspacing="0" cellpadding="4"{body_style}>',
    ]
    for index, (label, value) in enumerate(description_rows(description)):
        background = (
            f' style="background-color:{ALT_ROW_BACKGROUND_COLOR};"'
            if index % 2 == 0
            else ""
        )
        parts.append(
            f"<tr{background}><td><b>{escape_text(label)}</b></td>"
            f"<td>{escape_text(value)}</td></tr>",
        )
    parts.append("</table>")
    parts.extend(
        f'<br/><img src="{html.escape(filename, quote=True)}" />'
        for filename in image_filenames
    )
    return "<![CDATA[" + "".join(parts) + "]]>"
