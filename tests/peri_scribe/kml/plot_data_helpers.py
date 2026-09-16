"""Provide data builders and stand-ins for plot data tests."""

from __future__ import annotations

import dataclasses
import datetime
import typing

import hypothesis.strategies

import peri_scribe.incidents
import peri_scribe.kml.plot_data
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class ContainmentHistory:
    """Keep independent mapping and reporting streams beside their reference values."""

    measurements: tuple[peri_scribe.kml.plot_data.ExteriorMeasurement, ...]
    updates: tuple[peri_scribe.incidents.IncidentUpdate, ...]
    miles_by_time: dict[datetime.datetime, float]
    percent_by_time: dict[datetime.datetime, float]


@hypothesis.strategies.composite
def containment_histories(draw: hypothesis.strategies.DrawFn) -> ContainmentHistory:
    """Vary interleaved reports, absent measurements, zero values, and length units.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        The two input streams and their known measurements in reference units.
    """
    lengths = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.integers(0, 30),
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(0, 10_000).map(lambda value: value / 10),
            ),
            max_size=12,
        ),
    )
    percentages = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.integers(0, 30),
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.integers(0, 100),
            ),
            max_size=12,
        ),
    )
    length_unit = draw(
        hypothesis.strategies.sampled_from(["miles", "kilometers", "feet"]),
    )
    base = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    measurements = tuple(
        peri_scribe.kml.plot_data.ExteriorMeasurement(
            observation_time=base + datetime.timedelta(days=day),
            length=None if length is None else (length * units.miles).to(length_unit),
        )
        for day, length in sorted(lengths.items())
    )
    updates = tuple(
        peri_scribe.incidents.IncidentUpdate(
            observation_time=base + datetime.timedelta(days=day),
            report_time=None,
            confirmed=False,
            source="wfigs_location",
            source_file=f"{day}.gpkg",
            serial=day,
            measurements={}
            if percent is None
            else {"percent_contained": float(percent)},
        )
        for day, percent in sorted(percentages.items())
    )
    return ContainmentHistory(
        measurements=measurements,
        updates=updates,
        miles_by_time={
            base + datetime.timedelta(days=day): length
            for day, length in lengths.items()
            if length is not None
        },
        percent_by_time={
            base + datetime.timedelta(days=day): float(percent)
            for day, percent in percentages.items()
            if percent is not None
        },
    )


def series_points() -> hypothesis.strategies.SearchStrategy[
    tuple[peri_scribe.kml.plot_data.SeriesPoint, ...]
]:
    """Include reported and mapped measurements when testing plot transformations.

    Returns:
        Points with inferred observation times and bounded finite measurement values.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.builds(
            peri_scribe.kml.plot_data.SeriesPoint,
            value=hypothesis.strategies.floats(-1_000_000, 1_000_000),
            reported=...,
        ),
        max_size=20,
    ).map(tuple)


def make_perimeter_measurement_recorder(
    *,
    calls: list[shapely.Geometry | None],
    original: typing.Callable[..., pint.Quantity[float] | None],
) -> typing.Callable[..., pint.Quantity[float] | None]:
    """Create a callback with controlled dependencies.

    Count perimeter measurements while preserving their real results.

    Args:
        calls: Shared list recording dependency calls for assertions.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def counting_measure(
        geometry: shapely.Geometry | None,
    ) -> pint.Quantity[float] | None:
        """Count perimeter measurements while preserving their real results.

        Args:
            geometry: Geometry supplied for the selected spatial case.

        Returns:
            The measured exterior perimeter, or None for unusable geometry.
        """
        calls.append(geometry)
        return original(geometry)

    return counting_measure
