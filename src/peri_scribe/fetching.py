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
    existing_source_files: list[peri_scribe.snapshots.SourceFile],
    source_directory: pathlib.Path,
    *,
    full: bool = False,
) -> geopandas.GeoDataFrame | None:
    """Fetch a feed's new or changed features, or None when there are none.

    When *full* is true the whole layer is fetched and features already stored
    identically are dropped, so the fetch stores only new or changed features and
    writes nothing when the stored snapshots already cover the layer. Otherwise,
    when *existing_source_files* is empty the whole layer is fetched in full; when
    the store holds data, features modified since the stored data, minus a small
    overlap, are fetched, plus features that are present in the layer but never
    stored, plus stored-active features whose status flipped to inactive, and
    features already stored identically are dropped.

    Args:
        feed: The feed to fetch.
        layer: The layer to query.
        existing_source_files: The feed's stored source files, in serial order.
        source_directory: The directory holding the feed's snapshots.
        full: Fetch the whole layer instead of only changed features.

    Returns:
        The GeoDataFrame of features to write, or None when nothing changed.

    Raises:
        ValueError: If the feed has no change columns configured and *full* is
            false.
    """
    if not existing_source_files:
        feature_set = peri_scribe.geo_data.query_with_retry(feed.name, layer)
        return peri_scribe.geo_data.dataframe_for_layer(feed, layer, feature_set)
    if full:
        feature_set = peri_scribe.geo_data.query_with_retry(feed.name, layer)
        geodataframe = peri_scribe.geo_data.dataframe_for_layer(
            feed,
            layer,
            feature_set,
        )
        existing = peri_scribe.changes.existing_features(source_directory, feed)
        geodataframe = peri_scribe.changes.drop_features_already_present(
            geodataframe,
            existing,
        )
        if geodataframe.empty:
            logger.debug("No new or changed features", feed=feed.name)
            return None
        return geodataframe
    change_columns = feed.change_columns
    if not change_columns:
        message = f"Feed {feed.name} has no change columns configured"
        raise ValueError(message)
    existing = peri_scribe.changes.existing_features(source_directory, feed)
    cutoff = peri_scribe.changes.incremental_cutoff(existing, feed)
    where = peri_scribe.changes.where_clause_for(change_columns, cutoff)
    changed_ids = peri_scribe.geo_data.query_object_ids_with_retry(
        feed.name,
        layer,
        where=where,
    )
    # A source may publish features without updating their modified timestamps, so
    # the timestamp query alone can miss features that are present in the layer but
    # never stored (for example a WFIGS row re-added with an old modified time).
    # Compare the layer's full OBJECTID set against the stored set to catch them.
    stored_ids = peri_scribe.changes.stored_object_ids(existing)
    layer_ids = set(
        peri_scribe.geo_data.query_object_ids_with_retry(
            feed.name,
            layer,
            where="1=1",
        ),
    )
    missing_ids = sorted(layer_ids - stored_ids)
    if missing_ids:
        logger.debug(
            "Found features present but not stored",
            feed=feed.name,
            count=len(missing_ids),
        )
    active_ids = peri_scribe.changes.stored_status_object_ids(
        existing,
        feed,
        peri_scribe.models.FireStatus.ACTIVE,
    )
    inactive_literals = peri_scribe.changes.stored_status_literals(
        existing,
        feed,
        peri_scribe.models.FireStatus.INACTIVE,
    )
    flipped_ids: list[int] = []
    if active_ids and inactive_literals:
        # A source may flip a stored feature's status to inactive without updating
        # its modified timestamp, so re-check the stored-active features' statuses.
        flipped_ids = peri_scribe.geo_data.query_object_ids_with_retry(
            feed.name,
            layer,
            where=(
                f"{feed.status_column} IN ({', '.join(inactive_literals)}) "
                f"AND {peri_scribe.models.OBJECT_ID_COLUMN_NAME} "
                f"IN ({', '.join(str(i) for i in active_ids)})"
            ),
        )
    if flipped_ids:
        logger.debug(
            "Found stored-active features now inactive",
            feed=feed.name,
            count=len(flipped_ids),
        )
    object_ids = sorted(set(changed_ids) | set(missing_ids) | set(flipped_ids))
    if not object_ids:
        logger.debug("No new or changed features", feed=feed.name)
        return None
    feature_set = peri_scribe.geo_data.query_with_retry(
        feed.name,
        layer,
        parameters={"object_ids": ",".join(str(i) for i in object_ids)},
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
        logger.debug("No new or changed features", feed=feed.name)
        return None
    return geodataframe


def fetch_feed(
    feed: peri_scribe.feed_types.Feed,
    gis: arcgis.gis.GIS,
    existing_source_files: list[peri_scribe.snapshots.SourceFile],
    source_directory: pathlib.Path,
    *,
    full: bool = False,
) -> geopandas.GeoDataFrame | None:
    """Fetch a feed's new or changed features, or None when there are none.

    Failures are translated into a FeedFetchError so that the caller can report them
    without aborting the remaining feeds.

    Args:
        feed: The feed to fetch.
        gis: The ArcGIS connection used to open the feed's layer.
        existing_source_files: The feed's stored source files, in serial order.
        source_directory: The directory holding the feed's snapshots.
        full: Fetch the whole layer instead of only changed features.

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
            existing_source_files,
            source_directory,
            full=full,
        )
    except Exception as error:
        message = f"Failed to fetch {feed.name}: {error}"
        raise peri_scribe.exceptions.FeedFetchError(message) from error


def fetch_all_feeds(
    base_dir: pathlib.Path | None = None,
    *,
    year: int | None = None,
    full: bool = False,
) -> FetchResult:
    """Fetch each configured feed into its own GeoPackage snapshot.

    A feed with no stored snapshots is fetched in full. When *full* is true every
    feed is fetched in full, and only new or changed features are stored, so a full
    fetch writes nothing when the stored snapshots already cover the layer. This
    catches source edits that change features without moving their modified
    timestamps, which the incremental fetch would miss, and never modifies existing
    snapshots. Otherwise a feed that already has snapshots is fetched incrementally:
    only new or changed features are downloaded and written to a new snapshot. When a
    snapshot for the observed last-edit timestamp already exists, the feed is skipped
    entirely because the data is already present; a full fetch bypasses that skip.

    A feed that fails does not stop the other feeds from being fetched. When at least
    one feed writes a new snapshot, the fire source index is rebuilt so that it reflects
    the newly written snapshots. When any feed fails, all of the failures are reported
    together after the remaining feeds and the re-index have been attempted.

    Args:
        base_dir: Directory under which the ``data`` directory tree is created.
            Defaults to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.
        full: Fetch every feed in full instead of incrementally.

    Returns:
        The outcome of the fetch: the paths to the GeoPackage files holding each
        feed's data, one per feed, in feed order, and whether any feed wrote a new
        snapshot. A feed that produced no new snapshot contributes its most recent
        existing snapshot path instead.

    Raises:
        SystemExit: If any feed is unreachable, returns no features, cannot observe a
            last-edit timestamp, or lacks change columns for an incremental fetch.
            The message lists every feed that failed.
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
        logger.debug("Fetching", feed=feed.name, url=feed.url)
        last_edit_timestamp = feed.current_last_edit_timestamp
        if last_edit_timestamp is None:
            errors.append(
                f"Failed to fetch {feed.name}: "
                "no last-edit timestamp could be observed",
            )
            continue
        source_directory = peri_scribe.snapshots.source_directory_path(
            base_dir,
            year,
            feed.name,
        )
        if not full:
            existing_path = peri_scribe.snapshots.snapshot_path_for_last_edit_timestamp(
                source_directory,
                last_edit_timestamp,
            )
            if existing_path is not None:
                logger.debug(
                    "Skipping fetch; data already present",
                    feed=feed.name,
                    last_edit_timestamp=last_edit_timestamp,
                    path=existing_path,
                )
                snapshot_paths.append(existing_path)
                continue
        existing_source_files = peri_scribe.snapshots.existing_source_files(
            source_directory,
        )
        try:
            geodataframe = fetch_feed(
                feed,
                gis,
                existing_source_files,
                source_directory,
                full=full,
            )
        except peri_scribe.exceptions.FeedFetchError as error:
            errors.append(str(error))
            continue
        if geodataframe is None:
            latest_path = peri_scribe.changes.latest_snapshot_path(
                source_directory,
                existing_source_files,
            )
            if latest_path is not None:
                snapshot_paths.append(latest_path)
            continue
        logger.debug("Received features", count=len(geodataframe))
        logger.debug(
            "Prepared feed",
            feed=feed.name,
            rows=len(geodataframe),
            crs=geodataframe.crs,
        )
        serial_number = peri_scribe.snapshots.next_serial_number(
            existing_source_files,
            last_edit_timestamp,
            reuse_same_timestamp=not full,
        )
        output_path = peri_scribe.snapshots.source_geopackage_path(
            base_dir,
            year,
            feed.name,
            peri_scribe.snapshots.SourceFile(
                serial_number=serial_number,
                last_edit_timestamp=last_edit_timestamp,
            ),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Writing layer", feed=feed.name, path=output_path)
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
    logger.debug("Done")
    return FetchResult(
        snapshot_paths=tuple(snapshot_paths),
        changed=wrote_snapshot,
    )


def fetch_all_feeds_complete(
    base_dir: pathlib.Path | None = None,
    *,
    year: int | None = None,
) -> tuple[pathlib.Path, ...]:
    """Fetch every configured feed in full into the sources-complete directory.

    Every feed is fetched in full, regardless of what snapshots already exist, and
    written to its own GeoPackage under ``sources-complete``. A feed that fails does
    not stop the other feeds from being fetched, and all of the failures are reported
    together after the remaining feeds have been attempted.

    Args:
        base_dir: Directory under which the ``data`` directory tree is created.
            Defaults to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.

    Returns:
        The paths to the GeoPackage files holding each feed's complete data, one per
        feed, in feed order.

    Raises:
        SystemExit: If any feed is unreachable or returns no features. The message
            lists every feed that failed.
    """
    if base_dir is None:
        base_dir = pathlib.Path.cwd()
    if year is None:
        year = datetime.date.today().year
    gis = arcgis.gis.GIS()
    year_directory = peri_scribe.snapshots.year_directory_path(base_dir, year)
    snapshot_paths: list[pathlib.Path] = []
    errors: list[str] = []
    for feed in peri_scribe.feeds.FEEDS:
        logger.debug("Fetching complete snapshot", feed=feed.name, url=feed.url)
        try:
            geodataframe = fetch_feed(
                feed,
                gis,
                [],
                peri_scribe.snapshots.sources_complete_directory_path(
                    year_directory,
                ),
            )
        except peri_scribe.exceptions.FeedFetchError as error:
            errors.append(str(error))
            continue
        if geodataframe is None:
            errors.append(f"Failed to fetch {feed.name}: fetch produced no data")
            continue
        output_path = peri_scribe.snapshots.sources_complete_geopackage_path(
            year_directory,
            feed.name,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Writing layer", feed=feed.name, path=output_path)
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
    if errors:
        raise SystemExit("\n".join(errors))
    logger.debug("Done")
    return tuple(snapshot_paths)
