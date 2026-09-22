"""Shared fire facts and plain-text formatting for reports and map balloons."""

from __future__ import annotations

import dataclasses
import datetime
import math
import typing

import peri_scribe.perimeters.progression
from measurement_units import units


if typing.TYPE_CHECKING:
    import pint


# Areas at or above this size are shown as whole acres; smaller areas keep one or two
# decimal places so small fires do not read as zero.
WHOLE_AREA_THRESHOLD = 100.0 * units.acres

# A fire at or above this containment percentage is fully contained and needs no
# contained-length annotation.
FULL_CONTAINMENT = 100.0 * units.percent

# Perimeter lengths keep at most this many digits after the decimal point and at most
# this many significant digits, so a large fire's perimeter keeps its scale without
# implying more precision than the mapping supports.
MAXIMUM_PERIMETER_DECIMAL_PLACES = 1
MAXIMUM_PERIMETER_SIGNIFICANT_DIGITS = 3

# At one decimal place, lengths at or above this carry more than three significant
# digits and are re-rounded to three.
PERIMETER_SIGNIFICANT_DIGIT_THRESHOLD = 100.0 * units.miles

# The labels for the facts the report's summary headings name, spelled here because the
# report and the balloon both show these facts and a shared spelling keeps their tables
# in step.
AREA_LABEL = "Area"
DISCOVERY_LABEL = "Discovery"


def format_number(value: float | None, decimal_places: int = 0) -> str | None:
    """Format *value* with thousands separators and *decimal_places* decimals.

    Args:
        value: The number to format, or None.
        decimal_places: The number of decimal places to keep, or 0 for a whole number.

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


def format_area(value: pint.Quantity[float] | None) -> str | None:
    """Format an area in acres with a unit and size-appropriate precision.

    Args:
        value: The area to format, or None.

    Returns:
        The formatted area, like ``102,003 acres`` or ``6.5 acres``, or None.

    Examples:
        >>> format_area(6.5 * units.acres)
        '6.5 acres'
    """
    if value is None:
        return None
    if abs(value) >= WHOLE_AREA_THRESHOLD:
        number = format_number(value.m_as("acres"))
    elif abs(value) >= 1 * units.acres:
        number = format_number(value.m_as("acres"), 1)
    else:
        number = format_number(value.m_as("acres"), 2)
    return f"{number} acres"


def format_percent(value: float | None) -> str | None:
    """Format a containment percentage with a percent sign.

    Args:
        value: The percentage, or None.

    Returns:
        The formatted percentage, like ``77%``, or None.

    Examples:
        >>> format_percent(77)
        '77%'

        >>> format_percent(0.5)
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


def format_perimeter_length(value: pint.Quantity[float] | None) -> str | None:
    """Format a perimeter length in miles, with a capped precision.

    The length is rounded to at most one decimal place and to at most three significant
    digits: ``0.1499`` becomes ``0.1``, ``3.1415`` becomes ``3.1``, ``123.6`` becomes
    ``124``, and ``5678.123`` becomes ``5,680``.

    Args:
        value: The length to format, or None.

    Returns:
        The formatted length, or None when *value* is None.

    Examples:
        >>> format_perimeter_length(3.1415 * units.miles)
        '3.1'

        >>> format_perimeter_length(5678.123 * units.miles)
        '5,680'
    """
    if value is None:
        return None
    rounded = round(value.m_as("miles"), MAXIMUM_PERIMETER_DECIMAL_PLACES)
    if abs(rounded) >= PERIMETER_SIGNIFICANT_DIGIT_THRESHOLD.m_as("miles"):
        rounded = round_to_significant_digits(
            rounded,
            MAXIMUM_PERIMETER_SIGNIFICANT_DIGITS,
        )
    return format_number(rounded, MAXIMUM_PERIMETER_DECIMAL_PLACES)


def format_miles(value: pint.Quantity[float] | None) -> str | None:
    """Format a length in miles with a unit.

    Args:
        value: The length to format, or None.

    Returns:
        The formatted length, like ``33.1 miles``, or None.

    Examples:
        >>> format_miles(33.14 * units.miles)
        '33.1 miles'
    """
    if value is None:
        return None
    return f"{format_perimeter_length(value)} miles"


def format_containment(
    percent_contained: float | None,
    exterior_perimeter: pint.Quantity[float] | None,
) -> str | None:
    """Format a containment percentage, annotated with its contained length.

    When the exterior perimeter length is known the percentage is followed by the length
    it represents: ``68% (22.5 of 33.1 miles)``, where the last number is the exterior
    perimeter length and the first number in parentheses is that percentage of it. A
    fire that is fully contained (100%) shows only the percentage, as does a fire
    without a perimeter length; without a percentage there is nothing to show.

    Args:
        percent_contained: The containment percentage, or None.
        exterior_perimeter: The exterior perimeter length, or None.

    Returns:
        The formatted containment, or None.

    Examples:
        >>> format_containment(68, 33.1 * units.miles)
        '68% (22.5 of 33.1 miles)'
    """
    if percent_contained is None:
        return None
    percent_text = format_percent(percent_contained)
    if exterior_perimeter is None:
        return percent_text
    if percent_contained >= FULL_CONTAINMENT.m_as("percent"):
        return percent_text
    contained = percent_contained / 100.0 * exterior_perimeter
    return (
        f"{percent_text} ({format_perimeter_length(contained)} of "
        f"{format_perimeter_length(exterior_perimeter)} miles)"
    )


def format_cost(value: pint.Quantity[float] | None) -> str | None:
    """Format a cost in whole dollars with a dollar sign.

    Args:
        value: The cost, or None.

    Returns:
        The formatted cost, like ``$104,600,000``, or None.

    Examples:
        >>> format_cost(104600000 * units.dollars)
        '$104,600,000'
    """
    if value is None:
        return None
    return f"${format_number(value.m_as('dollars'))}"


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
    return format_number(value)


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
        ...     datetime.datetime(2025, 8, 2, 5, 30, tzinfo=datetime.UTC)
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
    """The latest state of a fire, ready for map and report descriptions."""

    identifier: str | None = None
    source: str | None = None
    mission: str | None = None
    area: pint.Quantity[float] | None = None
    exterior_perimeter: pint.Quantity[float] | None = None
    percent_contained: float | None = None
    estimated_cost_to_date: pint.Quantity[float] | None = None
    estimated_final_cost: pint.Quantity[float] | None = None
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
    area_basis: str | None = None


def description_rows(description: FireDescription) -> list[tuple[str, str | None]]:
    """Return the label/value rows shown in *description*'s balloon.

    Every fact the balloon's table shows appears once in its reading order, with None as
    the value when the fire lacks that fact, so each renderer decides how to show
    absence: the balloon's HTML shows two hyphens and the reports leave the row out.
    Because the balloon and the reports both build their tables from these rows, the two
    keep the same facts, labels, and text.

    Args:
        description: The fire's latest state.

    Returns:
        The display rows, in reading order, with None where a value is missing.
    """
    return [
        (AREA_LABEL, format_area(description.area)),
        *(
            [("Area basis", description.area_basis)]
            if description.area_basis is not None
            else []
        ),
        ("Exterior perimeter", format_miles(description.exterior_perimeter)),
        (
            "Containment",
            format_containment(
                description.percent_contained,
                description.exterior_perimeter,
            ),
        ),
        ("Cost to date", format_cost(description.estimated_cost_to_date)),
        ("Estimated final cost", format_cost(description.estimated_final_cost)),
        ("Personnel", format_personnel_count(description.total_personnel)),
        ("Source", description.source),
        ("Identifier", description.identifier),
        ("Mission", description.mission),
        ("Protecting unit", description.protecting_unit),
        (DISCOVERY_LABEL, format_pacific_time(description.discovery_time)),
        ("Last update", format_pacific_time(description.observation_time)),
        ("Initial response", format_pacific_time(description.initial_response_time)),
        ("Incident type", description.incident_type),
        ("Incident complexity", description.incident_complexity),
        ("Fuel model", description.fuel_model),
        ("Fire behavior", description.fire_behavior),
        ("Landowner category", description.landowner_category),
        ("Of note", description.of_note),
    ]
