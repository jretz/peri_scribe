"""Keep distant anonymous fires distinct through real grouped source evidence."""

from __future__ import annotations

import datetime
import pathlib
import typing

import shapely

import peri_scribe.fires.files
import peri_scribe.fires.history
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.index
import peri_scribe.sources.feeds


if typing.TYPE_CHECKING:
    import geopandas


def sources(directory: pathlib.Path) -> peri_scribe.fires.sources.ReadFireSources:
    """Use two source rows that name grouping must leave geographically separate.

    Args:
        directory: Isolated source root for the immutable snapshot paths.

    Returns:
        Anonymous California and Alaska namesakes with different mapped histories.
    """
    feed = peri_scribe.sources.feeds.WFIGS_PERIMETERS_FEED
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord(
                record=peri_scribe.models.FireRecord(
                    name="Canyon",
                    names=frozenset({"canyon"}),
                    status=peri_scribe.models.FireStatus.ACTIVE,
                    geometry=geometry,
                    observed_at=datetime.datetime(2026, 9, 25, tzinfo=datetime.UTC),
                ),
                object_id=number,
                source_name=feed.name,
                attributes={"poly_GISAcres": number * 100},
            )
            for number, geometry in enumerate(
                (
                    shapely.box(-121.5, 36.2, -121.4, 36.3),
                    shapely.box(-149.5, 64.2, -149.4, 64.3),
                ),
                start=1,
            )
        ),
        paths=(directory / feed.name / "000000,lastEdit=1790294400000.gpkg",) * 2,
        memberships=(),
    )


def histories(
    read: peri_scribe.fires.sources.ReadFireSources,
    directory: pathlib.Path,
) -> tuple[
    peri_scribe.models.FireIndex,
    geopandas.GeoDataFrame,
    geopandas.GeoDataFrame,
]:
    """Build index and full history from exactly the same grouped source rows.

    Args:
        read: Immutable source snapshots already read into typed records.
        directory: Their common source directory.

    Returns:
        A real fire index, full perimeter history, and empty point history.
    """
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    perimeters, points = peri_scribe.fires.history.history_layer_rows(
        groups,
        {},
        list(read.rows),
        list(read.paths),
        directory,
    )
    index = peri_scribe.fires.index.fire_index_document(
        peri_scribe.fires.index.fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(groups),
            directory,
        ),
    )
    return (
        index,
        peri_scribe.fires.history.build_dataframe(
            perimeters,
            peri_scribe.fires.files.PERIMETER_COLUMNS,
        ),
        typing.cast(
            "geopandas.GeoDataFrame",
            peri_scribe.fires.history.build_dataframe(
                points,
                peri_scribe.fires.files.POINT_COLUMNS,
            ).reindex(columns=peri_scribe.fires.files.POINT_COLUMNS),
        ),
    )


def summaries(
    read: peri_scribe.fires.sources.ReadFireSources,
    directory: pathlib.Path,
) -> list[peri_scribe.presentation.fire_data.FireSummary]:
    """Reach summary identities through the real qualification and selection path.

    Args:
        read: Source evidence before grouping.
        directory: Root of those sources.

    Returns:
        Qualified summaries with their own mapped histories.
    """
    index, perimeters, points = histories(read, directory)
    prepared = peri_scribe.presentation.index.prepare_histories(
        index,
        perimeters,
        points,
    )
    qualified = peri_scribe.presentation.index.area_qualified_index(
        index,
        perimeters,
        points,
        histories=prepared,
    )
    return peri_scribe.presentation.fire_data.fire_summaries(
        qualified,
        perimeters,
        points,
        perimeters.iloc[0:0],
        histories=prepared,
    )
