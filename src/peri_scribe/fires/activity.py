"""Refine agency activity using independent cumulative acreage histories.

[Policy and verification](../../../docs/algorithms/fire-activity.md)
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import operator
import typing

import peri_scribe.models
from measurement_units import units


if typing.TYPE_CHECKING:
    import collections.abc

    import pint


SHORT_WINDOW = datetime.timedelta(days=3)
LONG_WINDOW = datetime.timedelta(days=7)
MINIMUM_GROWTH = 10.0 * units.acres
LONG_AREA_GROWTH = 25.0 * units.acres
SHORT_GROWTH_FRACTION = 0.005
LONG_GROWTH_FRACTION = 0.01


@dataclasses.dataclass(frozen=True, kw_only=True)
class AreaObservation:
    """Keep a dated acreage measurement on its own reported or mapped basis."""

    time: datetime.datetime
    area: pint.Quantity[float]


@dataclasses.dataclass(frozen=True, kw_only=True)
class GrowthWindow:
    """Distinguish a missing baseline from measured zero growth."""

    baseline_area: pint.Quantity[float] | None
    growth: pint.Quantity[float]


def utc_time(time: datetime.datetime) -> datetime.datetime:
    """Compare elapsed windows in UTC, interpreting naive input as UTC.

    Args:
        time: A source or reference instant.

    Returns:
        The equivalent UTC instant.
    """
    return (
        time.replace(tzinfo=datetime.UTC)
        if time.utcoffset() is None
        else time.astimezone(datetime.UTC)
    )


def visible_observations(
    observations: collections.abc.Sequence[AreaObservation],
    reference_time: datetime.datetime,
) -> tuple[AreaObservation, ...]:
    """Select finite past measurements and retain the last same-time correction.

    Args:
        observations: One acreage basis in source order, with explicit area units.
        reference_time: Inclusive upper observation bound.

    Returns:
        Usable nonnegative observations in chronological UTC order.
    """
    reference_time = utc_time(reference_time)
    by_time: dict[datetime.datetime, AreaObservation] = {}
    for observation in observations:
        time = utc_time(observation.time)
        area = observation.area.to("acres")
        if (
            time <= reference_time
            and math.isfinite(area.magnitude)
            and area >= 0 * units.acres
        ):
            by_time[time] = AreaObservation(time=time, area=area)
    return tuple(sorted(by_time.values(), key=operator.attrgetter("time")))


def growth_window(
    observations: collections.abc.Sequence[AreaObservation],
    reference_time: datetime.datetime,
    window: datetime.timedelta,
) -> GrowthWindow:
    """Measure peak excess over the latest observation at the window's start.

    Args:
        observations: Independent reported or full mapped acreage measurements.
        reference_time: Inclusive end of the window.
        window: Elapsed lookback duration.

    Returns:
        The baseline acreage and nonnegative peak excess. A missing baseline has zero
        measured growth and must be handled separately by the initial-history policy.
    """
    past = visible_observations(observations, reference_time)
    cutoff = utc_time(reference_time) - window
    baseline: pint.Quantity[float] | None = None
    peak = 0.0 * units.acres
    for observation in past:
        if observation.time <= cutoff:
            baseline = observation.area
            peak = baseline
        else:
            peak = max(peak, observation.area)
    return GrowthWindow(
        baseline_area=baseline,
        growth=0.0 * units.acres if baseline is None else peak - baseline,
    )


def stream_active(
    observations: collections.abc.Sequence[AreaObservation],
    reference_time: datetime.datetime,
) -> bool:
    """Keep initial streams or streams meeting either cumulative threshold Active.

    Args:
        observations: Measurements sharing one acreage basis.
        reference_time: The publication's assessment instant.

    Returns:
        Whether this stream provides an Active signal. An absent stream provides none.
    """
    past = visible_observations(observations, reference_time)
    if not past:
        return False
    short = growth_window(past, reference_time, SHORT_WINDOW)
    if short.baseline_area is None:
        return True
    if short.growth > max(
        MINIMUM_GROWTH,
        short.baseline_area * SHORT_GROWTH_FRACTION,
    ):
        return True
    long = growth_window(past, reference_time, LONG_WINDOW)
    return (
        long.baseline_area is not None
        and long.growth > MINIMUM_GROWTH
        and (
            long.growth > LONG_AREA_GROWTH
            or long.growth > long.baseline_area * LONG_GROWTH_FRACTION
        )
    )


def active_status(
    source_status: peri_scribe.models.FireStatus,
    reported: collections.abc.Sequence[AreaObservation],
    mapped: collections.abc.Sequence[AreaObservation],
    reference_time: datetime.datetime,
) -> peri_scribe.models.FireStatus:
    """Refine agency Active without requiring recent updates to establish Holding.

    Args:
        source_status: The agency-derived Active or Inactive status.
        reported: Incident acreage observations, independently reconciled.
        mapped: Full mapped measurements on their own observation clock.
        reference_time: The publication's assessment instant.

    Returns:
        Inactive for agency Inactive; otherwise Active for unknown or initial history
        or either growth signal, and Holding for the remaining established histories.
    """
    if source_status is peri_scribe.models.FireStatus.INACTIVE:
        return source_status
    reported = visible_observations(reported, reference_time)
    mapped = visible_observations(mapped, reference_time)
    if (
        (not reported and not mapped)
        or stream_active(reported, reference_time)
        or stream_active(mapped, reference_time)
    ):
        return peri_scribe.models.FireStatus.ACTIVE
    return peri_scribe.models.FireStatus.HOLDING
