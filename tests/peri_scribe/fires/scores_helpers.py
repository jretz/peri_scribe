"""Provide data builders and stand-ins for scores tests."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import hypothesis.strategies

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas

    import peri_scribe.sources.external_data


@dataclasses.dataclass(frozen=True, kw_only=True)
class ScoreObservation:
    """Retain independent source measurements for per-fire aggregation checks.

    Args:
        key: The fire identifier shared by its observations.
        hour: The observation's offset from the reference date, or None when undated.
        reported_area: The reported acreage, or None when missing.
        reported_growth: The reported growth in acres, or None when missing.
        calculated_area: The geometry acreage, or None when missing.
        calculated_growth: The geometry growth in acres, or None when missing.
    """

    key: str
    hour: int | None
    reported_area: float | None
    reported_growth: float | None
    calculated_area: float | None
    calculated_growth: float | None


@hypothesis.strategies.composite
def score_histories(draw: hypothesis.strategies.DrawFn) -> list[ScoreObservation]:
    """Interleave fires with missing observations and disagreeing source measurements.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Measurements with unique times per fire, including possible undated records.
    """
    area = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(0, 10_000),
    )
    growth = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.integers(-1000, 10_000),
    )
    rows = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.tuples(
                hypothesis.strategies.sampled_from(["a", "b", "c"]),
                hypothesis.strategies.one_of(
                    hypothesis.strategies.none(),
                    hypothesis.strategies.integers(-5, 5),
                ),
            ),
            hypothesis.strategies.tuples(area, growth, area, growth),
            max_size=12,
        ),
    )
    return [
        ScoreObservation(
            key=key,
            hour=hour,
            reported_area=reported_area,
            reported_growth=reported_growth,
            calculated_area=calculated_area,
            calculated_growth=calculated_growth,
        )
        for (key, hour), (
            reported_area,
            reported_growth,
            calculated_area,
            calculated_growth,
        ) in rows.items()
    ]


def metric_frame(
    observations: list[ScoreObservation],
    *,
    use_geometry: bool,
) -> geopandas.GeoDataFrame:
    """Build history with repeated index labels and optional geometry measurements.

    Args:
        observations: Measurements to aggregate in their input order.
        use_geometry: Whether the history includes persisted geometry measurements.

    Returns:
        A perimeter history frame whose row labels cannot be treated as row positions.
    """
    base = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    frame = tests.factories.geo_frame(
        {
            "fire_name": [item.key for item in observations],
            "fire_identifier": [item.key for item in observations],
            "observation_time": [
                None
                if item.hour is None
                else base + datetime.timedelta(hours=item.hour)
                for item in observations
            ],
            "area_acres": [item.reported_area for item in observations],
            "area_acres_differential": [item.reported_growth for item in observations],
            "area_acres_from_geometry": [item.calculated_area for item in observations],
            "area_acres_from_geometry_differential": [
                item.calculated_growth for item in observations
            ],
        },
        [None] * len(observations),
    )
    frame.index = [index % 3 - 1 for index in range(len(observations))]
    if not use_geometry:
        frame.drop(
            columns=[
                "area_acres_from_geometry",
                "area_acres_from_geometry_differential",
            ],
            inplace=True,
        )
    return frame


def make_external_output_path(
    *,
    tmp_path: pathlib.Path,
) -> typing.Callable[..., pathlib.Path]:
    """Create a callback to keep external-source reads inside the test directory.

    Args:
        tmp_path: Isolated directory used by the callback.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def output_path(
        _year_directory: pathlib.Path,
        source: peri_scribe.sources.external_data.ExternalSource,
        **kwargs: object,
    ) -> pathlib.Path:
        """Keep external-source reads inside the test directory.

        Args:
            _year_directory: Unused production year directory.
            source: The source whose storage format determines the suffix.
            kwargs: Unused source path options.

        Returns:
            The isolated SQLite or GeoPackage source path.
        """
        suffix = ".sqlite" if source.compact_database else ".gpkg"
        return tmp_path / "sources" / source.name / f"{source.name}{suffix}"

    return output_path
