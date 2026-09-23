"""Keep migration regression inputs isolated from retained application data."""

import dataclasses
import datetime
import pathlib
import unittest.mock

import click.testing
import geopandas
import pandas as pd
import shapely

import migrations.backfill_fire_updates
import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.publication


def history_inputs(
    builds: list[migrations.backfill_fire_updates.Build],
) -> migrations.backfill_fire_updates.Inputs:
    """Provide empty histories for testing replay evidence and output preservation.

    Args:
        builds: Successful runs evidenced by diagnostic logs.

    Returns:
        Isolated reconstruction inputs without external source dependencies.
    """
    history = geopandas.GeoDataFrame(
        {"available_at": pd.to_datetime([], utc=True)},
        geometry=[],
        crs="EPSG:4326",
    )
    return migrations.backfill_fire_updates.Inputs(
        builds=builds,
        perimeters=history,
        points=history,
        incidents=history,
        index=peri_scribe.models.FireIndex(version="1", fires=[]),
    )


def invoke_backfill(
    directory: pathlib.Path,
    inputs: migrations.backfill_fire_updates.Inputs,
    arguments: tuple[str, ...] = (),
) -> click.testing.Result:
    """Exercise Click error handling while isolating input loading from the replay.

    Args:
        directory: Temporary root holding copied inputs and staged output.
        inputs: Explicit historical evidence for this invocation.
        arguments: Additional Click options for the reconstruction.

    Returns:
        The command's output and exit status.
    """
    year = directory / "copied-year"
    year.mkdir()
    with (
        unittest.mock.patch.object(
            migrations.backfill_fire_updates,
            "read_inputs",
            return_value=inputs,
        ),
        unittest.mock.patch.object(
            migrations.backfill_fire_updates,
            "input_checksums",
            return_value={},
        ),
    ):
        return click.testing.CliRunner().invoke(
            migrations.backfill_fire_updates.main,
            [str(year), str(directory / "output"), *arguments],
        )


def replay_inputs(
    perimeter_days: tuple[int, ...],
) -> migrations.backfill_fire_updates.Inputs:
    """Distinguish builds with new mapping from successful runs requiring no replay.

    Args:
        perimeter_days: September dates on which a new perimeter became available.

    Returns:
        Three successive completed builds with the requested perimeter availability.
    """
    inputs = history_inputs([
        migrations.backfill_fire_updates.Build(cutoff=completed, completed=completed)
        for day in range(1, 4)
        for completed in [datetime.datetime(2026, 9, day, tzinfo=datetime.UTC)]
    ])
    perimeters = geopandas.GeoDataFrame(
        {
            "available_at": pd.to_datetime(
                [f"2026-09-{day:02}" for day in perimeter_days],
                utc=True,
            ),
        },
        geometry=[shapely.Point(day, 0) for day in perimeter_days],
        crs="EPSG:4326",
    )
    return dataclasses.replace(inputs, perimeters=perimeters)


def prepared_build(
    build: migrations.backfill_fire_updates.Build,
) -> peri_scribe.fire_updates.PreparedUpdates:
    """Make the emitted checkpoint identify the actual last replayed build.

    Args:
        build: The build whose mapping baseline is acknowledged.

    Returns:
        A baseline stamped with this build's completion time.
    """
    return peri_scribe.fire_updates.PreparedUpdates(
        records=(),
        state=peri_scribe.fire_updates.State(
            perimeters={"Timber": frozenset({build.completed.isoformat()})},
        ),
    )


def captured_mappings() -> peri_scribe.publication.Collection:
    """Distinguish original shape captures from the retained source file's timestamp.

    Returns:
        One nullable and one integer source identifier with different captures.
    """
    source = "perimeters/source.gpkg"
    captured = datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC)
    return peri_scribe.publication.Collection(
        files={
            source: peri_scribe.publication.FileStamp(
                size=100,
                modified_nanoseconds=int(captured.timestamp() * 1_000_000_000),
            ),
        },
        mappings={
            source: tuple(
                peri_scribe.publication.Mapping(
                    source_file=source,
                    object_id=identifier,
                    identifiers=(),
                    name="Timber",
                    observed_at=None,
                    captured_at=captured - datetime.timedelta(days=offset + 1),
                    serial=offset,
                    shape=str(offset),
                    area_square_meters=100.0,
                )
                for offset, identifier in enumerate((None, 123))
            ),
        },
    )


def nullable_history() -> geopandas.GeoDataFrame:
    """Represent the float coercion caused by mixed missing and integer source IDs.

    Returns:
        History whose missing source ID is pandas NaN rather than Python None.
    """
    return geopandas.GeoDataFrame(
        {
            "source_file": ["perimeters/source.gpkg"] * 2,
            "source_objectid": [None, 123],
            "observation_time": pd.to_datetime([None, None], utc=True),
        },
        geometry=[shapely.Point(0, 0), shapely.Point(1, 1)],
        crs="EPSG:4326",
    )


def output_files(directory: pathlib.Path) -> dict[pathlib.Path, bytes]:
    """Retain exact staged artifacts so rejection cannot silently replace evidence.

    Args:
        directory: The temporary output directory.

    Returns:
        Every regular output file and its bytes.
    """
    return {
        path.relative_to(directory): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }
