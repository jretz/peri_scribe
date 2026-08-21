"""Fetching feed data from ArcGIS into snapshot GeoPackages."""

from __future__ import annotations

import dataclasses
import datetime
import pathlib
import typing

import arcgis.features
import arcgis.gis
import structlog

import peri_scribe.changes
import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.feeds
import peri_scribe.fire_index
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True, kw_only=True)
class FetchResult:
    """The outcome of fetching every configured feed."""

    snapshot_paths: tuple[pathlib.Path, ...]
    changed: bool


def fetch_feed_dataframe(
    feed: peri_scribe.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    existing_filenames: list[pathlib.Path],
    source_directory: pathlib.Path,
) -> geopandas.GeoDataFrame | None:
    """Fetch a feed's new or changed features, or None when there are none.

    When *existing_filenames* is empty the whole layer is fetched in full. Otherwise
    only features modified since the stored data, minus a small overlap, are fetched,
    and features already stored identically are dropped.

    Args:
        feed: The feed to fetch.
        layer: The layer to query.
        existing_filenames: The feed's stored snapshot filenames, in serial order.
        source_directory: The directory holding the feed's snapshots.

    Returns:
        The GeoDataFrame of features to write, or None when nothing changed.

    Raises:
        ValueError: If the feed has no modified column configured.
    """
    if not existing_filenames:
        feature_set = peri_scribe.geo_data.query_with_retry(feed.name, layer)
        return peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)
    modified_column = feed.modified_column
    if modified_column is None:
        message = f"Feed {feed.name} has no modified column configured"
        raise ValueError(message)
    existing = peri_scribe.changes.existing_features(source_directory, feed)
    cutoff = peri_scribe.changes.incremental_cutoff(existing, feed)
    where = peri_scribe.changes.where_clause_for(modified_column, cutoff)
    changed_ids = peri_scribe.geo_data.query_object_ids_with_retry(
        feed.name,
        layer,
        where=where,
    )
    if not changed_ids:
        logger.info("No new or changed features", feed=feed.name)
        return None
    feature_set = peri_scribe.geo_data.query_with_retry(
        feed.name,
        layer,
        parameters={"object_ids": ",".join(str(i) for i in changed_ids)},
    )
    geodataframe = peri_scribe.geo_data.dataframe_for_layer(
        feed,
        layer,
        feature_set,
    )
    geodataframe = peri_scribe.changes.drop_features_already_present(
        geodataframe,
        existing,
    )
    if geodataframe.empty:
        logger.info("No new or changed features", feed=feed.name)
        return None
    return geodataframe


def fetch_feed(
    feed: peri_scribe.feed_types.Feed,
    gis: arcgis.gis.GIS,
    existing_filenames: list[pathlib.Path],
    source_directory: pathlib.Path,
) -> geopandas.GeoDataFrame | None:
    """Fetch a feed's new or changed features, or None when there are none.

    Failures are translated into a FeedFetchError so that the caller can report them
    without aborting the remaining feeds.

    Args:
        feed: The feed to fetch.
        gis: The ArcGIS connection used to open the feed's layer.
        existing_filenames: The feed's stored snapshot filenames, in serial order.
        source_directory: The directory holding the feed's snapshots.

    Returns:
        The GeoDataFrame of features to write, or None when nothing changed.

    Raises:
        FeedFetchError: If the feed cannot be fetched.
    """
    try:
        layer = arcgis.features.FeatureLayer(feed.url, gis)
        return fetch_feed_dataframe(
            feed,
            layer,
            existing_filenames,
            source_directory,
        )
    except Exception as error:
        message = f"Failed to fetch {feed.name}: {error}"
        raise peri_scribe.exceptions.FeedFetchError(message) from error


def fetch_all_feeds(
    base_dir: pathlib.Path | None = None,
    *,
    year: int | None = None,
) -> FetchResult:
    """Fetch each configured feed into its own GeoPackage snapshot.

    A feed with no stored snapshots is fetched in full. A feed that already has
    snapshots is fetched incrementally: only new or changed features are downloaded and
    written to a new snapshot, and existing snapshots are never modified. When a
    snapshot for the observed watermark already exists, the feed is skipped entirely
    because the data is already present.

    A feed that fails does not stop the other feeds from being fetched. When at least
    one feed writes a new snapshot, the fire source index is rebuilt so that it reflects
    the newly written snapshots. When any feed fails, all of the failures are reported
    together after the remaining feeds and the re-index have been attempted.

    Args:
        base_dir: Directory under which the ``data`` directory tree is created.
            Defaults to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.

    Returns:
        The outcome of the fetch: the paths to the GeoPackage files holding each
        feed's data, one per feed, in feed order, and whether any feed wrote a new
        snapshot. A feed that produced no new snapshot contributes its most recent
        existing snapshot path instead.

    Raises:
        SystemExit: If any feed is unreachable, returns no features, cannot observe a
            watermark, or lacks a modified column for an incremental fetch. The message
            lists every feed that failed.
    """
    if base_dir is None:
        base_dir = pathlib.Path.cwd()
    if year is None:
        year = datetime.date.today().year
    gis = arcgis.gis.GIS()
    snapshot_paths: list[pathlib.Path] = []
    errors: list[str] = []
    wrote_snapshot = False
    for feed in peri_scribe.feeds.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        watermark = feed.current_watermark
        if watermark is None:
            errors.append(
                f"Failed to fetch {feed.name}: no watermark could be observed",
            )
            continue
        source_directory = (
            base_dir
            / peri_scribe.output.DATA_DIRECTORY
            / str(year)
            / peri_scribe.snapshots.SOURCES_DIRECTORY_NAME
            / feed.name
        )
        existing_path = peri_scribe.snapshots.snapshot_path_for_watermark(
            source_directory,
            watermark,
        )
        if existing_path is not None:
            logger.info(
                "Skipping fetch; data already present",
                feed=feed.name,
                watermark=watermark,
                path=existing_path,
            )
            snapshot_paths.append(existing_path)
            continue
        existing_filenames = peri_scribe.snapshots.existing_geopackage_filenames(
            source_directory,
        )
        try:
            geodataframe = fetch_feed(
                feed,
                gis,
                existing_filenames,
                source_directory,
            )
        except peri_scribe.exceptions.FeedFetchError as error:
            errors.append(str(error))
            continue
        if geodataframe is None:
            latest_path = peri_scribe.changes.latest_snapshot_path(
                source_directory,
                existing_filenames,
            )
            if latest_path is not None:
                snapshot_paths.append(latest_path)
            continue
        logger.info("Received features", count=len(geodataframe))
        logger.info(
            "Prepared feed",
            feed=feed.name,
            rows=len(geodataframe),
            crs=geodataframe.crs,
        )
        serial_number = peri_scribe.snapshots.next_serial_number(
            existing_filenames,
            watermark,
        )
        output_path = peri_scribe.snapshots.source_geopackage_path(
            base_dir,
            year,
            feed.name,
            serial_number,
            watermark,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Writing layer", feed=feed.name, path=output_path)
        peri_scribe.output.write_geopackage(
            output_path,
            [
                peri_scribe.models.LayerData(
                    name=feed.name,
                    dataframe=geodataframe,
                ),
            ],
        )
        snapshot_paths.append(output_path)
        wrote_snapshot = True
    if wrote_snapshot:
        peri_scribe.fire_index.index_fire_sources(
            peri_scribe.snapshots.year_directory_path(base_dir, year),
        )
    if errors:
        raise SystemExit("\n".join(errors))
    logger.info("Done")
    return FetchResult(
        snapshot_paths=tuple(snapshot_paths),
        changed=wrote_snapshot,
    )
