"""Fetching feed data from ArcGIS into snapshot GeoPackages.

Design notes:
[Incremental source collection](../../../docs/algorithms/source-collection.md).
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import functools
import importlib
import pathlib
import tempfile
import typing

import structlog

import arcgis_access.client as arcgis
import peri_scribe.concurrency
import peri_scribe.exceptions
import peri_scribe.logging
import peri_scribe.paths
import peri_scribe.phases
import peri_scribe.sources.feed_types
import peri_scribe.sources.feeds
import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()
FetchResult = peri_scribe.sources.snapshots.FetchResult


def fetch_feed_dataframe(
    feed: peri_scribe.sources.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    existing_source_files: list[peri_scribe.sources.snapshots.SourceFile],
    source_directory: pathlib.Path,
    *,
    full: bool = False,
) -> geopandas.GeoDataFrame | None:
    """Fetch a feed's new or changed features, or None when there are none.

    A full fetch reads the entire layer, as does an initial fetch with no stored
    snapshots. An incremental fetch reads changes since the latest stored timestamp,
    with a small overlap to catch updates near that boundary. It also checks for IDs
    never stored and active features that have become inactive, since those changes can
    occur without an updated timestamp.

    Rows already stored with identical content are dropped in either case. A full
    download therefore produces no new snapshot when the stored history covers it.

    Args:
        feed: The feed to fetch.
        layer: The layer to query.
        existing_source_files: The feed's stored source files, in serial order.
        source_directory: The directory holding the feed's snapshots.
        full: Fetch the whole layer instead of only changed features.

    Returns:
        The GeoDataFrame of features to write, or None when nothing changed.

    Raises:
        ValueError: If the feed has no change columns configured and *full* is false.
    """
    geo_data = importlib.import_module("peri_scribe.geo.data")
    if not existing_source_files:
        feature_set = geo_data.query_with_retry(feed.name, layer)
        return geo_data.dataframe_for_layer(feed, layer, feature_set)
    changes = importlib.import_module("peri_scribe.sources.changes")
    feed_state = importlib.import_module("peri_scribe.sources.feed_state")
    if full:
        feature_set = geo_data.query_with_retry(feed.name, layer)
        geodataframe = geo_data.dataframe_for_layer(
            feed,
            layer,
            feature_set,
        )
        existing = feed_state.read_current_features(
            source_directory,
            feed,
        )
        with peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.COMPARE_FEATURES,
            feed=feed.name,
        ):
            geodataframe = changes.drop_features_already_present(
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
    existing = feed_state.read_current_features(
        source_directory,
        feed,
    )
    incremental_query = importlib.import_module("peri_scribe.sources.incremental_query")
    object_ids = incremental_query.object_ids(feed, layer, change_columns, existing)
    if not object_ids:
        logger.debug("No new or changed features", feed=feed.name)
        return None
    feature_set = geo_data.query_with_retry(
        feed.name,
        layer,
        parameters={"object_ids": ",".join(str(i) for i in object_ids)},
    )
    geodataframe = geo_data.dataframe_for_layer(feed, layer, feature_set)
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.COMPARE_FEATURES,
        feed=feed.name,
    ):
        geodataframe = changes.drop_features_already_present(
            geodataframe,
            existing,
        )
    if geodataframe.empty:
        logger.debug("No new or changed features", feed=feed.name)
        return None
    return geodataframe


def fetch_feed(
    feed: peri_scribe.sources.feed_types.Feed,
    gis: arcgis.gis.GIS,
    existing_source_files: list[peri_scribe.sources.snapshots.SourceFile],
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class FeedOutcome:
    """Keep independent feed failures separate from collection-wide publication."""

    path: pathlib.Path | None = None
    changed: bool = False
    error: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class CollectedFeeds:
    """Retain collection results before indexing and reporting source failures."""

    snapshot_paths: tuple[pathlib.Path, ...]
    errors: tuple[str, ...]
    changed: bool


FEED_CONCURRENCY = 3


async def collect_one_feed(
    fetch: typing.Callable[[peri_scribe.sources.feed_types.Feed], FeedOutcome],
    feed: peri_scribe.sources.feed_types.Feed,
    limit: asyncio.Semaphore,
) -> FeedOutcome:
    """Bound blocking SDK work and propagate each task's phase context.

    Args:
        fetch: The independent operation for one feed.
        feed: The source configuration.
        limit: Shared limit on in-flight feed operations.

    Returns:
        The outcome, including expected source failures.
    """
    async with limit:
        return await peri_scribe.concurrency.run_blocking(
            functools.partial(fetch, feed),
        )


async def collect_feeds(
    fetch: typing.Callable[[peri_scribe.sources.feed_types.Feed], FeedOutcome],
) -> list[FeedOutcome]:
    """Attempt all feeds concurrently while preserving configured result order.

    Args:
        fetch: An operation owning its feed's client and snapshot paths.

    Returns:
        Outcomes in feed order after every operation completes.
    """
    limit = asyncio.Semaphore(FEED_CONCURRENCY)
    async with asyncio.TaskGroup() as tasks:
        pending = [
            tasks.create_task(collect_one_feed(fetch, feed, limit))
            for feed in peri_scribe.sources.feeds.FEEDS
        ]
    return [task.result() for task in pending]


def collect_feed_outcomes(
    fetch: typing.Callable[[peri_scribe.sources.feed_types.Feed], FeedOutcome],
) -> tuple[FeedOutcome, ...]:
    """Join every feed operation before returning results to the collection policy.

    Args:
        fetch: The independent operation owning each feed's client and snapshot.

    Returns:
        The immutable outcomes in configured feed order.
    """
    return tuple(asyncio.run(collect_feeds(fetch)))


def summarize_feed_outcomes(outcomes: tuple[FeedOutcome, ...]) -> CollectedFeeds:
    """Keep publication decisions independent of worker and event-loop lifetimes.

    Args:
        outcomes: The joined outcomes in configured feed order.

    Returns:
        Saved paths, ordered source errors and whether any snapshot changed.
    """
    snapshot_paths = tuple(
        outcome.path for outcome in outcomes if outcome.path is not None
    )
    errors = tuple(outcome.error for outcome in outcomes if outcome.error is not None)
    wrote_snapshot = any(outcome.changed for outcome in outcomes)
    return CollectedFeeds(
        snapshot_paths=snapshot_paths,
        errors=errors,
        changed=wrote_snapshot,
    )


def open_feed_connection(
    feed: peri_scribe.sources.feed_types.Feed,
) -> arcgis.gis.GIS:
    """Keep SDK connection failures local to the affected feed.

    Args:
        feed: The source whose independent connection is being opened.

    Returns:
        A connection owned by this feed's worker.

    Raises:
        FeedFetchError: The SDK could not establish a connection.
    """
    try:
        return arcgis.gis.GIS()
    except Exception as error:
        message = f"Failed to fetch {feed.name}: {error}"
        raise peri_scribe.exceptions.FeedFetchError(message) from error


def fetch_feed_snapshot(
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    base_dir: pathlib.Path,
    year: int,
    full: bool,
) -> FeedOutcome:
    """Give each feed exclusive ownership of its connection and snapshot state.

    Args:
        feed: The configured feed to refresh.
        base_dir: Root containing the data tree.
        year: Snapshot year.
        full: Whether timestamp-based skipping is disabled.

    Returns:
        The saved snapshot, change flag, or expected source failure.
    """
    feed_state = importlib.import_module("peri_scribe.sources.feed_state")
    layers = importlib.import_module("spatial_data.layers")
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.COLLECT_FEED,
        feed=feed.name,
        url=feed.url,
    ):
        with peri_scribe.logging.log_phase(
            peri_scribe.phases.Phase.CHECK_METADATA,
            feed=feed.name,
        ):
            last_edit_timestamp = feed.current_last_edit_timestamp
        if last_edit_timestamp is None:
            return FeedOutcome(
                error=(
                    f"Failed to fetch {feed.name}: no last-edit timestamp "
                    "could be observed"
                ),
            )
        source_directory = peri_scribe.sources.snapshots.source_directory_path(
            base_dir,
            year,
            feed.name,
        )
        if not full:
            existing_path = (
                peri_scribe.sources.snapshots
            ).snapshot_path_for_last_edit_timestamp(
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
                return FeedOutcome(path=existing_path)
        existing_source_files = peri_scribe.sources.snapshots.existing_source_files(
            source_directory,
        )
        try:
            geodataframe = fetch_feed(
                feed,
                open_feed_connection(feed),
                existing_source_files,
                source_directory,
                full=full,
            )
        except peri_scribe.exceptions.FeedFetchError as error:
            return FeedOutcome(error=str(error))
        if geodataframe is None:
            latest_path = feed_state.latest_snapshot_path(
                source_directory,
                existing_source_files,
            )
            return FeedOutcome(path=latest_path)
        serial_number = peri_scribe.sources.snapshots.next_serial_number(
            existing_source_files,
            last_edit_timestamp,
            reuse_same_timestamp=not full,
        )
        output_path = peri_scribe.sources.snapshots.source_geopackage_path(
            base_dir,
            year,
            feed.name,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=serial_number,
                last_edit_timestamp=last_edit_timestamp,
            ),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            peri_scribe.logging.log_phase(
                peri_scribe.phases.Phase.WRITE_SNAPSHOT,
                feed=feed.name,
                path=output_path,
                rows=len(geodataframe),
                crs=geodataframe.crs,
            ),
            tempfile.TemporaryDirectory(dir=output_path.parent) as directory,
        ):
            # Recursive discovery must reject names in abandoned staging directories.
            temporary = pathlib.Path(directory) / "snapshot.gpkg"
            layers.write_geopackage(
                temporary,
                [
                    layers.LayerData(
                        name=feed.name,
                        dataframe=geodataframe,
                    ),
                ],
            )
            temporary.replace(output_path)
        try:
            with peri_scribe.logging.log_phase(
                peri_scribe.phases.Phase.UPDATE_CURRENT_STATE,
                feed=feed.name,
            ):
                feed_state.write_current_state(
                    source_directory,
                    feed,
                    geodataframe,
                )
        except (OSError, RuntimeError, ValueError) as error:
            # The current-state file is only a derived cache. If its update fails, the
            # snapshots still hold the source data and the next fetch can rebuild it.
            logger.warning(
                "Failed to update current state",
                feed=feed.name,
                error=str(error),
                exc_info=True,
            )
        return FeedOutcome(path=output_path, changed=True)


def fetch_all_feeds(
    base_dir: pathlib.Path | None = None,
    *,
    year: int | None = None,
    full: bool = False,
    build_index: bool = True,
) -> FetchResult:
    """Fetch each configured feed into its own GeoPackage snapshot.

    A feed with no stored snapshots is fetched in full. When *full* is true every feed
    is fetched in full, and only new or changed features are stored, so a full fetch
    writes nothing when the stored snapshots already cover the layer. This catches
    source edits that change features without moving their modified timestamps, which
    the incremental fetch would miss, and never modifies existing snapshots. Otherwise a
    feed that already has snapshots is fetched incrementally: candidate additions and
    edits are retrieved, and only new or changed features are written to a new snapshot.
    When a snapshot for the observed last-edit timestamp already exists, the feed is
    skipped entirely. That shortcut assumes the timestamp advances for relevant edits;
    a full fetch bypasses it.

    A feed that fails does not stop the other feeds from being fetched. When
    *build_index* is true, the fire source index is rebuilt after a full fetch or when
    any feed writes a new snapshot. Failures are reported together after the remaining
    feeds and any requested index rebuild have been attempted.

    Args:
        base_dir: Directory under which the ``data`` directory tree is created. Defaults
            to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.
        full: Fetch every feed in full instead of incrementally.
        build_index: Refresh the derived source index before returning. A publication
            gate can defer this work until it accepts the saved changes.

    Returns:
        The outcome of the fetch: the paths to the GeoPackage files holding each feed's
        data, one per feed, in feed order, and whether any feed wrote a new snapshot. A
        feed that produced no new snapshot contributes its most recent existing snapshot
        path instead.

    Raises:
        SystemExit: If any feed is unreachable, returns no features, cannot observe a
            last-edit timestamp, or lacks change columns for an incremental fetch. The
            message lists every feed that failed.
    """
    if base_dir is None:
        base_dir = pathlib.Path.cwd()
    if year is None:
        year = datetime.date.today().year
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.FIRE_COLLECTION):
        outcomes = collect_feed_outcomes(
            functools.partial(
                fetch_feed_snapshot,
                base_dir=base_dir,
                year=year,
                full=full,
            ),
        )
    collected = summarize_feed_outcomes(outcomes)
    snapshot_paths = collected.snapshot_paths
    errors = collected.errors
    wrote_snapshot = collected.changed
    if build_index and (wrote_snapshot or full):
        fire_index = importlib.import_module("peri_scribe.fires.index")
        fire_index.index_fire_sources(
            peri_scribe.paths.year_directory_path(base_dir, year),
        )
    if errors:
        raise SystemExit("\n".join(errors))
    return FetchResult(snapshot_paths=snapshot_paths, changed=wrote_snapshot)


def fetch_all_feeds_complete(
    base_dir: pathlib.Path | None = None,
    *,
    year: int | None = None,
) -> tuple[pathlib.Path, ...]:
    """Fetch every configured feed in full into the validation directory.

    Every feed is fetched in full, regardless of what snapshots already exist, and
    written to its own GeoPackage under ``validation``. A feed that fails does not stop
    the other feeds from being fetched, and all of the failures are reported together
    after the remaining feeds have been attempted.

    Args:
        base_dir: Directory under which the ``data`` directory tree is created. Defaults
            to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.

    Returns:
        The paths to the GeoPackage files holding each feed's complete data, one per
        feed, in feed order.

    Raises:
        SystemExit: If any feed is unreachable or returns no features. The message lists
            every feed that failed.
    """
    if base_dir is None:
        base_dir = pathlib.Path.cwd()
    if year is None:
        year = datetime.date.today().year
    year_directory = peri_scribe.paths.year_directory_path(base_dir, year)
    outcomes = asyncio.run(
        collect_feeds(
            functools.partial(
                fetch_validation_feed,
                year_directory=year_directory,
            ),
        ),
    )
    snapshot_paths = [outcome.path for outcome in outcomes if outcome.path is not None]
    errors = [outcome.error for outcome in outcomes if outcome.error is not None]
    if errors:
        raise SystemExit("\n".join(errors))
    logger.debug("Done")
    return tuple(snapshot_paths)


def fetch_validation_feed(
    feed: peri_scribe.sources.feed_types.Feed,
    *,
    year_directory: pathlib.Path,
) -> FeedOutcome:
    """Keep complete validation snapshots independent until collection finishes.

    Args:
        feed: The configured feed.
        year_directory: Root holding validation snapshots.

    Returns:
        The written path or the feed's source failure.
    """
    layers = importlib.import_module("spatial_data.layers")
    logger.debug("Fetching complete snapshot", feed=feed.name, url=feed.url)
    try:
        geodataframe = fetch_feed(
            feed,
            open_feed_connection(feed),
            [],
            peri_scribe.sources.snapshots.validation_directory_path(year_directory),
        )
    except peri_scribe.exceptions.FeedFetchError as error:
        return FeedOutcome(error=str(error))
    if geodataframe is None:
        return FeedOutcome(error=f"Failed to fetch {feed.name}: fetch produced no data")
    output_path = peri_scribe.sources.snapshots.validation_geopackage_path(
        year_directory,
        feed.name,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Writing layer", feed=feed.name, path=output_path)
    layers.write_geopackage(
        output_path,
        [layers.LayerData(name=feed.name, dataframe=geodataframe)],
    )
    return FeedOutcome(path=output_path, changed=True)
