"""Orchestration logic for peri_scribe — feed fetching, fire listing, output writing.

This module contains the core business logic shared across all user interfaces.
"""

from __future__ import annotations

import collections
import datetime
import pathlib
import typing

import arcgis.features
import arcgis.gis
import pandas as pd
import shapely
import structlog

import peri_scribe.exceptions
import peri_scribe.feed_types
import peri_scribe.geo_data
import peri_scribe.models
import peri_scribe.output


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()

DATA_DIRECTORY_NAME = "data"
SOURCES_DIRECTORY_NAME = "sources"
FIRE_INDEX_FILENAME = "fires.json"

# The current version of the fire source index format; bump it when the format
# changes so that consumers can tell which format a file uses.
FIRE_INDEX_VERSION = "2026-08-17"

# When fetching only changed features, the cutoff for the query is moved back by this
# amount so that recently edited features are re-fetched and re-checked rather than
# missed because of clock skew or in-flight edits.
OVERLAP = datetime.timedelta(minutes=5)

# Two fire geometries are treated as the same fire when they overlap or the gap between
# them is within this tolerance. It is expressed in degrees, which is roughly 5.5 km.
FIRE_PROXIMITY_TOLERANCE_DEGREES = 0.05

# A fire whose records are farther apart than this is reported as possibly two fires
# that were merged. It is far looser than the proximity tolerance so that a point
# location moving between snapshots does not raise a warning.
FIRE_OUTLIER_TOLERANCE_DEGREES = 1.0

# A fire whose records span longer than this across observation times is reported as
# possibly two fires that were merged.
FIRE_OBSERVATION_SPREAD_TOLERANCE = datetime.timedelta(days=60)

# The number of timed records needed to measure an observation-time spread.
MINIMUM_TIMED_RECORDS = 2

# The number of non-empty geometries needed before spatial compatibility can merge
# records or mark them as disagreeing.
MINIMUM_SPATIAL_GEOMETRIES = 2


def geopackage_filename(serial_number: int, watermark: str) -> pathlib.Path:
    """Return the filename for a snapshot with *serial_number* and *watermark*.

    Args:
        serial_number: The zero-padded serial number of the snapshot.
        watermark: The watermark observed for the snapshot.

    Returns:
        The snapshot's GeoPackage filename.
    """
    return pathlib.Path(f"{serial_number:06d},{watermark}.gpkg")


def parse_geopackage_filename(filename: pathlib.Path) -> tuple[int, str]:
    """Return the serial number and watermark encoded in *filename*.

    The watermark may itself contain commas, so only the first comma separates the
    serial number from the watermark.

    Args:
        filename: The GeoPackage filename to parse.

    Returns:
        The serial number and watermark encoded in *filename*.
    """
    serial_text, watermark = filename.stem.split(",", 1)
    return int(serial_text), watermark


def next_serial_number(
    existing_filenames: typing.Iterable[pathlib.Path],
    watermark: str,
) -> int:
    """Return the serial number to use for a snapshot named *watermark*.

    The serial number reuses the number of an existing snapshot for the same watermark,
    and otherwise is one greater than the largest serial number among
    *existing_filenames*, so the first snapshot for a source is numbered 0.

    Args:
        existing_filenames: The names of the source's existing GeoPackage files.
        watermark: The watermark to name the new snapshot with.

    Returns:
        The serial number for the new snapshot.
    """
    serial_numbers: list[int] = []
    matching_serial_numbers: list[int] = []
    for filename in existing_filenames:
        try:
            serial_number, existing_watermark = parse_geopackage_filename(filename)
        except ValueError:
            continue
        serial_numbers.append(serial_number)
        if existing_watermark == watermark:
            matching_serial_numbers.append(serial_number)
    if matching_serial_numbers:
        return max(matching_serial_numbers)
    return max(serial_numbers, default=-1) + 1


def existing_geopackage_filenames(directory: pathlib.Path) -> list[pathlib.Path]:
    """Return the names of the GeoPackage files in *directory*.

    Args:
        directory: The directory to list GeoPackage files from.

    Returns:
        The GeoPackage filenames, or an empty list when the directory is missing.
    """
    if not directory.is_dir():
        return []
    return sorted(
        pathlib.Path(path.name)
        for path in directory.iterdir()
        if path.suffix == ".gpkg"
    )


def geo_package_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Return the GeoPackage files under *directory*, in sorted order.

    The directory tree is searched recursively, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Sorting makes the order
    deterministic: feed directories by name, then snapshots by serial number.

    Args:
        directory: The directory tree to search.

    Returns:
        The GeoPackage file paths, in sorted order, or an empty list when *directory*
        does not exist.

    Raises:
        SystemExit: If the directory tree cannot be read.
    """
    if not directory.is_dir():
        return []
    try:
        return sorted(directory.rglob("*.gpkg"))
    except OSError as error:
        message = f"Failed to read {directory}: {error}"
        raise SystemExit(message) from error


def snapshot_path_for_watermark(
    directory: pathlib.Path,
    watermark: str,
) -> pathlib.Path | None:
    """Return the path of the existing snapshot named *watermark* in *directory*.

    Args:
        directory: The directory holding the source's GeoPackage files.
        watermark: The watermark to look for.

    Returns:
        The path of the snapshot whose filename encodes *watermark*, or None when
        *directory* has no such snapshot. Malformed filenames are ignored.
    """
    for filename in existing_geopackage_filenames(directory):
        try:
            _, filename_watermark = parse_geopackage_filename(filename)
        except ValueError:
            continue
        if filename_watermark == watermark:
            return directory / filename
    return None


def source_geopackage_path(
    base_dir: pathlib.Path,
    year: int,
    source_name: str,
    serial_number: int,
    watermark: str,
) -> pathlib.Path:
    """Return the path where *source_name*'s snapshot is stored.

    Snapshots are stored under
    ``base_dir/data/{year}/sources/{source_name}/{serial},{watermark}.gpkg``.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year the snapshot belongs to.
        source_name: The name of the source the snapshot came from.
        serial_number: The serial number of the snapshot.
        watermark: The watermark that names the snapshot.

    Returns:
        The path to the snapshot's GeoPackage file.
    """
    return (
        sources_directory_path(year_directory_path(base_dir, year))
        / source_name
        / geopackage_filename(serial_number, watermark)
    )


def year_directory_path(base_dir: pathlib.Path, year: int) -> pathlib.Path:
    """Return the directory that holds *year*'s data under *base_dir*.

    Args:
        base_dir: The base directory that holds the ``data`` directory.
        year: The year whose data directory is returned.

    Returns:
        The path to the year's data directory.
    """
    return base_dir / DATA_DIRECTORY_NAME / str(year)


def sources_directory_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the sources directory inside *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's sources directory.
    """
    return year_directory / SOURCES_DIRECTORY_NAME


def fire_index_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the fire index for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The path to the year's fire index file.
    """
    return sources_directory_path(year_directory) / FIRE_INDEX_FILENAME


def parse_iso_datetime(text: str) -> datetime.datetime | None:
    """Parse an ISO-8601 datetime string, or return None when invalid.

    Args:
        text: The datetime string to parse.

    Returns:
        The parsed datetime, or None when *text* is blank or invalid.
    """
    try:
        return datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        return None


def modified_datetime_from(value: object) -> datetime.datetime | None:
    """Parse a modified timestamp value into an aware UTC datetime.

    ArcGIS date fields arrive as epoch milliseconds in query responses and as ISO-8601
    strings or pandas timestamps when read back from a GeoPackage. Blank values are
    treated as missing.

    Args:
        value: The raw modified timestamp value.

    Returns:
        The parsed UTC datetime, or None when *value* is blank or not parseable.
    """
    if peri_scribe.geo_data.is_missing(value):
        return None

    parsed: datetime.datetime | None
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = parse_iso_datetime(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = datetime.datetime.fromtimestamp(value / 1000.0, tz=datetime.UTC)
    else:
        parsed = None

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def existing_features(
    directory: pathlib.Path,
    feed: peri_scribe.feed_types.Feed,
) -> geopandas.GeoDataFrame | None:
    """Return the latest stored feature per OBJECTID across *directory*'s files.

    Files are read in serial order, so a later file's version of a feature supersedes an
    earlier one. Returns None when the directory holds no feature data to compare
    against.

    Args:
        directory: The directory holding the source's GeoPackage files.
        feed: The feed whose layer is read from each file.

    Returns:
        The most recent feature per OBJECTID, or None when there are none.
    """
    dataframes = [
        peri_scribe.geo_data.read_layer_dataframe(directory / filename, feed)
        for filename in existing_geopackage_filenames(directory)
    ]
    if not dataframes:
        return None
    combined = typing.cast(
        "geopandas.GeoDataFrame",
        pd.concat(dataframes, ignore_index=True),
    )
    if "OBJECTID" not in combined.columns:
        return None
    return combined[~combined.duplicated(subset=["OBJECTID"], keep="last")]


def latest_modified_datetime(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime | None:
    """Return the latest modified timestamp across the stored features.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the modified timestamp column.

    Returns:
        The latest modified UTC datetime, or None when none can be found.
    """
    if existing is None or existing.empty:
        return None
    modified_column = feed.modified_column
    if modified_column is None or modified_column not in existing.columns:
        return None
    values = [modified_datetime_from(value) for value in existing[modified_column]]
    latest = [value for value in values if value is not None]
    if not latest:
        return None
    return max(latest)


def incremental_cutoff(
    existing: geopandas.GeoDataFrame | None,
    feed: peri_scribe.feed_types.Feed,
) -> datetime.datetime:
    """Return the cutoff for an incremental fetch.

    The cutoff is the latest stored modified timestamp minus the overlap, so that
    recently edited features are re-fetched and re-checked rather than missed because of
    clock skew or in-flight edits. When no stored timestamp can be found, the Unix epoch
    is used so the query returns every feature for deduplication to filter.

    Args:
        existing: The latest stored feature per OBJECTID, or None.
        feed: The feed providing the modified timestamp column.

    Returns:
        The aware UTC cutoff timestamp.
    """
    latest = latest_modified_datetime(existing, feed)
    if latest is None:
        return datetime.datetime.fromtimestamp(0, tz=datetime.UTC)
    return latest - OVERLAP


def where_clause_for(
    modified_column: str,
    cutoff: datetime.datetime,
) -> str:
    """Return a where clause selecting features modified at or after *cutoff*.

    Args:
        modified_column: The feed's modified timestamp column.
        cutoff: The aware UTC cutoff timestamp.

    Returns:
        The SQL where clause for an ArcGIS query.
    """
    iso = cutoff.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{modified_column} >= timestamp '{iso}Z'"


def normalized_attribute_value(value: object) -> object:
    """Return *value* with missing and sub-second timestamps normalized.

    Pandas missing values are mapped to None so equal rows compare equal, and datetimes
    are truncated to whole seconds so the server's inconsistent fractional-second
    serialization does not make identical rows look different.

    Args:
        value: An attribute value from a feature row.

    Returns:
        The comparable form of *value*.
    """
    if peri_scribe.geo_data.is_missing(value):
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0)
    return value


def attribute_columns(
    new_dataframe: geopandas.GeoDataFrame,
    existing_dataframe: geopandas.GeoDataFrame,
) -> list[str]:
    """Return the attribute columns shared by two feature dataframes.

    The geometry column of each dataframe is excluded. Columns are ordered as they
    appear in *new_dataframe* so that signatures from both dataframes line up.

    Args:
        new_dataframe: The newly fetched features.
        existing_dataframe: The stored features to compare against.

    Returns:
        The shared attribute column names.
    """
    existing_columns = set(existing_dataframe.columns) - {
        existing_dataframe.geometry.name,
    }
    return [
        column
        for column in new_dataframe.columns
        if column != new_dataframe.geometry.name and column in existing_columns
    ]


def feature_signature(
    values: dict[str, object],
    columns: list[str],
    geometry: object,
) -> tuple[tuple[object, ...], bytes | None]:
    """Return the content signature of a single feature row.

    The signature combines the row's normalized attribute values with the well-known
    binary of its geometry, so two features are identical only when both their
    attributes and their geometry match.

    Args:
        values: The row's attribute values, keyed by column name.
        columns: The attribute columns to include in the signature.
        geometry: The row's geometry, or None when the feature has none.

    Returns:
        The feature's content signature.
    """
    attributes = tuple(normalized_attribute_value(values[column]) for column in columns)
    shapely_geometry = typing.cast("shapely.Geometry | None", geometry)
    geometry_key = shapely_geometry.wkb if shapely_geometry is not None else None
    return (attributes, geometry_key)


def feature_signatures(
    dataframe: geopandas.GeoDataFrame,
    columns: list[str],
) -> dict[int, tuple[tuple[object, ...], bytes | None]]:
    """Return each feature's content signature, keyed by OBJECTID.

    The signature combines the feature's normalized attribute values with the well-known
    binary of its geometry, so two features are identical only when both their
    attributes and their geometry match.

    Args:
        dataframe: The features to sign.
        columns: The attribute columns to include in each signature.

    Returns:
        The signatures, keyed by OBJECTID.
    """
    geometry_name = dataframe.geometry.name
    signatures: dict[int, tuple[tuple[object, ...], bytes | None]] = {}
    for row in dataframe.itertuples(index=False, name=None):
        values = dict(zip(dataframe.columns, row, strict=True))
        object_id = int(values["OBJECTID"])
        signatures[object_id] = feature_signature(
            values,
            columns,
            values[geometry_name],
        )
    return signatures


def drop_features_already_present(
    new_dataframe: geopandas.GeoDataFrame,
    existing_dataframe: geopandas.GeoDataFrame | None,
) -> geopandas.GeoDataFrame:
    """Drop fetched features whose content is already stored identically.

    A feature is kept when its OBJECTID is new, or when its stored content differs from
    the freshly fetched content. Features with a matching OBJECTID and identical
    attributes and geometry are dropped.

    Args:
        new_dataframe: The newly fetched features.
        existing_dataframe: The latest stored feature per OBJECTID, or None.

    Returns:
        The features that are new or changed.
    """
    if existing_dataframe is None or existing_dataframe.empty:
        return new_dataframe
    columns = attribute_columns(new_dataframe, existing_dataframe)
    existing_signatures = feature_signatures(existing_dataframe, columns)
    geometry_name = new_dataframe.geometry.name
    keep: list[bool] = []
    for row in new_dataframe.itertuples(index=False, name=None):
        values = dict(zip(new_dataframe.columns, row, strict=True))
        object_id = int(values["OBJECTID"])
        keep.append(
            existing_signatures.get(object_id)
            != feature_signature(values, columns, values[geometry_name]),
        )
    return new_dataframe[keep].reset_index(drop=True)


def latest_snapshot_path(
    directory: pathlib.Path,
    existing_filenames: list[pathlib.Path],
) -> pathlib.Path | None:
    """Return the most recent snapshot path, or None when there are none.

    Args:
        directory: The directory holding the source's GeoPackage files.
        existing_filenames: The source's GeoPackage filenames, in serial order.

    Returns:
        The path of the most recent snapshot, or None when there are none.
    """
    if not existing_filenames:
        return None
    return directory / existing_filenames[-1]


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
    existing = existing_features(source_directory, feed)
    cutoff = incremental_cutoff(existing, feed)
    where = where_clause_for(modified_column, cutoff)
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
    geodataframe = drop_features_already_present(geodataframe, existing)
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
) -> tuple[pathlib.Path, ...]:
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
        The paths to the GeoPackage files holding each feed's data, one per feed, in
        feed order. A feed that produced no new snapshot contributes its most recent
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
    for feed in peri_scribe.models.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        watermark = feed.current_watermark
        if watermark is None:
            errors.append(
                f"Failed to fetch {feed.name}: no watermark could be observed",
            )
            continue
        source_directory = (
            base_dir
            / DATA_DIRECTORY_NAME
            / str(year)
            / SOURCES_DIRECTORY_NAME
            / feed.name
        )
        existing_path = snapshot_path_for_watermark(source_directory, watermark)
        if existing_path is not None:
            logger.info(
                "Skipping fetch; data already present",
                feed=feed.name,
                watermark=watermark,
                path=existing_path,
            )
            snapshot_paths.append(existing_path)
            continue
        existing_filenames = existing_geopackage_filenames(source_directory)
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
            latest_path = latest_snapshot_path(source_directory, existing_filenames)
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
        serial_number = next_serial_number(existing_filenames, watermark)
        output_path = source_geopackage_path(
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
        index_fire_sources(year_directory_path(base_dir, year))
    if errors:
        raise SystemExit("\n".join(errors))
    logger.info("Done")
    return tuple(snapshot_paths)


def fire_sources(directory: pathlib.Path) -> list[peri_scribe.models.FireSources]:
    """Collect the distinct fires and their source files under *directory*.

    Every GeoPackage file anywhere below *directory* is read, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Fire records sharing any identifier
    are the same fire; records sharing only a name are merged only when they are
    spatially compatible, so distinct fires that happen to share a name (e.g. "Canyon"
    in California vs. Alaska) stay separate. The
    most common spelling of each name is the one kept, and a fire is active when any of
    its records is active. A fire whose records are spatially or temporally spread out
    is reported with a warning. Fires that are complex parents are represented by a
    FireComplex instead of listed as fires, and member fires carry a circular link to
    their complex.

    Each result records the GeoPackage files whose rows mention the fire, so the same
    fire can be traced back to every snapshot it appears in.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The fires, in the order first encountered, each with the paths of the GeoPackage
        files that mention it.

    Raises:
        SystemExit: If a GeoPackage file cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    records: list[peri_scribe.models.FireRecord] = []
    record_paths: list[pathlib.Path] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for path in geo_package_files(directory):
        try:
            file_records = list(peri_scribe.geo_data.fire_records(path))
            file_memberships = list(
                peri_scribe.geo_data.complex_memberships(path),
            )
        except peri_scribe.exceptions.UnknownLayerError:
            raise
        except Exception as error:
            # Fail fast with a readable message if a GeoPackage is unreadable.
            message = f"Failed to read {path}: {error}"
            raise SystemExit(message) from error
        records.extend(file_records)
        record_paths.extend([path] * len(file_records))
        memberships.extend(file_memberships)
    groups = group_fire_record_indices(records)
    fires = [most_common_fire([records[index] for index in group]) for group in groups]
    warn_for_inconsistent_fires(records, groups, fires)
    fires_by_identifier: dict[str, peri_scribe.models.Fire] = {}
    for group, fire in zip(groups, fires, strict=True):
        for index in group:
            for identifier in records[index].identifiers:
                fires_by_identifier.setdefault(identifier, fire)
    complexes = fire_complexes(memberships, fires_by_identifier)
    complex_identifiers = {complex_.identifier for complex_ in complexes}
    sources: list[peri_scribe.models.FireSources] = []
    for fire, group in zip(fires, groups, strict=True):
        if any(
            identifier in complex_identifiers
            for index in group
            for identifier in records[index].identifiers
        ):
            continue
        sources.append(
            peri_scribe.models.FireSources(
                fire=fire,
                paths=tuple(
                    sorted({record_paths[index] for index in group}),
                ),
            ),
        )
    return sources


def fire_document(fire: peri_scribe.models.Fire) -> dict[str, object]:
    """Return a JSON-serializable document describing *fire*.

    A fire in a complex is described with the complex's name and identifier. The
    complex's member list is not included, because it links back to the fire and would
    make the document circular.

    Args:
        fire: The fire to describe.

    Returns:
        The fire's attributes as a JSON-serializable dictionary.
    """
    complex_document: dict[str, object] | None
    if fire.complex is None:
        complex_document = None
    else:
        complex_document = {
            "name": fire.complex.name,
            "identifier": fire.complex.identifier,
        }
    return {
        "name": fire.name,
        "status": fire.status.value,
        "identifier": fire.identifier,
        "aliases": sorted(fire.aliases),
        "complex": complex_document,
    }


def fire_sources_document(
    source: peri_scribe.models.FireSources,
    sources_directory: pathlib.Path,
) -> dict[str, object]:
    """Return a JSON-serializable document for *source*.

    The document has all of the fire's attributes plus the paths of the GeoPackage files
    that mention it, relative to *sources_directory* and sorted by path.

    Args:
        source: The fire and its source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.

    Returns:
        The fire and its source paths as a JSON-serializable dictionary.
    """
    return {
        **fire_document(source.fire),
        "paths": sorted(
            str(path.relative_to(sources_directory)) for path in source.paths
        ),
    }


def fire_index_entries(
    sources: list[peri_scribe.models.FireSources],
    sources_directory: pathlib.Path,
) -> list[dict[str, object]]:
    """Return the fire index documents for *sources*, sorted by fire name.

    Args:
        sources: The fires and their source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.

    Returns:
        One document per fire, sorted by fire name.
    """
    return [
        fire_sources_document(source, sources_directory)
        for source in sorted(sources, key=lambda source: source.fire.name)
    ]


def fire_index_document(
    entries: list[dict[str, object]],
) -> peri_scribe.models.FireIndex:
    """Validate *entries* as the fire index for the current version.

    Args:
        entries: The fire index entry documents.

    Returns:
        The validated fire index document.
    """
    return peri_scribe.models.FireIndex.model_validate({
        "version": FIRE_INDEX_VERSION,
        "fires": entries,
    })


def index_fire_sources(year_directory: pathlib.Path) -> None:
    """Build the fire source index for *year_directory*.

    The index lists every distinct fire in the GeoPackage files under
    ``{year_directory}/sources``, along with the GeoPackage files that mention each
    fire. It is written to ``{year_directory}/sources/fires.json``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
    """
    sources_directory = sources_directory_path(year_directory)
    index = fire_index_document(
        fire_index_entries(
            fire_sources(sources_directory),
            sources_directory,
        ),
    )
    output_path = fire_index_path(year_directory)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    peri_scribe.output.write_fire_index(output_path, index)


def load_fire_index(year_directory: pathlib.Path) -> peri_scribe.models.FireIndex:
    """Return the fire index for *year_directory*, building it first if needed.

    The index is read from ``{year_directory}/sources/fires.json``. When the file is
    missing, it is built from the GeoPackage files under the sources directory before
    it is read, so the index is always available once this returns.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The validated fire index.
    """
    index_path = fire_index_path(year_directory)
    if not index_path.is_file():
        index_fire_sources(year_directory)
    return peri_scribe.models.FireIndex.model_validate_json(
        index_path.read_text(encoding="utf-8"),
    )


def geometries_are_compatible(
    left: shapely.Geometry | None,
    right: shapely.Geometry | None,
    *,
    tolerance_degrees: float = FIRE_PROXIMITY_TOLERANCE_DEGREES,
) -> bool:
    """Return whether two fire geometries plausibly describe the same fire.

    Geometries describe the same fire when they overlap or the gap between them is
    within *tolerance_degrees*, so a point location and a perimeter of the same fire
    match while two same-named fires in different regions do not.

    Args:
        left: One geometry, or None.
        right: The other geometry, or None.
        tolerance_degrees: The maximum gap, in degrees, treated as the same fire.

    Returns:
        True when the geometries overlap or are within the tolerance.
    """
    if left is None or right is None or left.is_empty or right.is_empty:
        return False
    if left.intersects(right):
        return True
    return left.distance(right) <= tolerance_degrees


def nearby_pairs(
    geometries: list[shapely.Geometry],
    *,
    tolerance_degrees: float,
) -> typing.Iterator[tuple[int, int]]:
    """Yield the index pairs of *geometries* within *tolerance_degrees*.

    A spatial index limits the comparisons to geometries that are actually close, so
    the number of pairs grows with the number of nearby geometries rather than with
    the square of the list length. Each geometry is paired with itself, and each
    distinct pair appears in both directions, so callers can treat the result as the
    adjacency of a directed graph and skip self-pairs.

    Args:
        geometries: The geometries to compare.
        tolerance_degrees: The maximum distance, in degrees, that counts as nearby.

    Yields:
        Pairs of indices whose geometries are within the tolerance.
    """
    tree = shapely.STRtree(geometries)
    pairs = tree.query(
        geometries,
        predicate="dwithin",
        distance=tolerance_degrees,
    )
    for left, right in zip(pairs[0], pairs[1], strict=True):
        yield int(left), int(right)


def records_span_distant_locations(
    records: list[peri_scribe.models.FireRecord],
    group: list[int],
) -> bool:
    """Return whether a record in *group* disagrees with the rest on location.

    A record disagrees when the rest of the group has a geometry and the record has
    none, or when none of the other records' geometries is within the outlier
    tolerance; the distance from a record to the union of the others is the minimum
    distance to any one of them. A spatial index limits the comparisons to records
    that are actually close.

    Args:
        records: The records that were grouped.
        group: The record indices of one fire.

    Returns:
        True when some record disagrees with the rest of the group on location.
    """
    geometries_by_index: dict[int, shapely.Geometry] = {}
    for index in group:
        geometry = records[index].geometry
        if geometry is not None:
            geometries_by_index[index] = geometry
    members = [
        (index, geometry)
        for index, geometry in geometries_by_index.items()
        if not geometry.is_empty
    ]
    positions = {index: position for position, (index, _geometry) in enumerate(members)}
    has_other_match = [False] * len(members)
    if len(members) >= MINIMUM_SPATIAL_GEOMETRIES:
        for left, right in nearby_pairs(
            [geometry for _index, geometry in members],
            tolerance_degrees=FIRE_OUTLIER_TOLERANCE_DEGREES,
        ):
            if left != right:
                has_other_match[left] = True
    for index in group:
        geometry = records[index].geometry
        others_count = len(geometries_by_index) - (
            1 if index in geometries_by_index else 0
        )
        if others_count == 0:
            continue
        if (
            geometry is None
            or geometry.is_empty
            or not has_other_match[positions[index]]
        ):
            return True
    return False


def warn_for_inconsistent_fires(
    records: list[peri_scribe.models.FireRecord],
    groups: list[list[int]],
    fires: list[peri_scribe.models.Fire],
) -> None:
    """Log a warning for each fire whose records are spread across space or time.

    A fire whose member records disagree on location or span a long observation range
    may be two fires that were merged by name. The warning names the fire so the
    grouping can be inspected.

    Args:
        records: The records that were grouped.
        groups: The record indices of each fire, aligned with *fires*.
        fires: The fires, aligned with *groups*.
    """
    for fire, group in zip(fires, groups, strict=True):
        if records_span_distant_locations(records, group):
            logger.warning(
                "Fire records span distant locations",
                fire=fire.name,
                identifier=fire.identifier,
            )
        observed_times: list[datetime.datetime] = []
        for index in group:
            observed_at = records[index].observed_at
            if observed_at is not None:
                observed_times.append(observed_at)
        if len(observed_times) >= MINIMUM_TIMED_RECORDS:
            spread = max(observed_times) - min(observed_times)
            if spread > FIRE_OBSERVATION_SPREAD_TOLERANCE:
                logger.warning(
                    "Fire records span distant times",
                    fire=fire.name,
                    identifier=fire.identifier,
                    days=spread.days,
                )


def group_fire_records(
    records: list[peri_scribe.models.FireRecord],
) -> list[list[peri_scribe.models.FireRecord]]:
    """Group fire records that identify the same fire into a single list.

    Records sharing any identifier are the same fire. Records sharing only a name are
    the same fire when they are spatially compatible, so distinct fires that happen to
    share a name (e.g. "Canyon" in California vs. Alaska) stay separate.

    Args:
        records: The fire records to group.

    Returns:
        The groups of records, in the order first encountered.
    """
    return [
        [records[index] for index in group]
        for group in group_fire_record_indices(records)
    ]


def group_fire_record_indices(
    records: list[peri_scribe.models.FireRecord],
) -> list[list[int]]:
    """Group the indices of fire records that identify the same fire.

    The grouping rules are the same as `group_fire_records`, but each group holds the
    indices of its records instead of the records themselves, so callers can look up
    associated data such as each record's source file.

    Args:
        records: The fire records to group.

    Returns:
        The groups of record indices, in the order first encountered.
    """
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    # Records sharing any identifier are the same fire.
    by_identifier: dict[str, int] = {}
    for index, record in enumerate(records):
        for identifier in record.identifiers:
            if identifier in by_identifier:
                union(index, by_identifier[identifier])
            else:
                by_identifier[identifier] = index

    merge_records_by_name(records, union)

    groups_by_root: dict[int, list[int]] = {}
    order: list[int] = []
    for index in range(len(records)):
        root = find(index)
        if root not in groups_by_root:
            order.append(root)
            groups_by_root[root] = []
        groups_by_root[root].append(index)
    return [groups_by_root[root] for root in order]


def merge_records_by_name(
    records: list[peri_scribe.models.FireRecord],
    union: typing.Callable[[int, int], None],
) -> None:
    """Merge records that share a name and are spatially compatible.

    Records sharing a name are grouped by spatial proximity, whether or not they have
    identifiers. A same-named fire is the same fire wherever it is mapped, even when
    different rows carry different identifiers (for example a re-mapping that received a
    new GUID), so any two same-named records whose geometries are compatible are one
    fire. Fires with the same name in different regions stay separate because their
    geometries are not compatible. A spatial index limits the compatibility checks to
    records whose geometries are actually close, so a name shared by many distant fires
    (e.g. "Canyon" in California vs. Alaska) does not make the grouping quadratic.

    Args:
        records: The records to merge.
        union: The union-find union used by the grouping.
    """
    by_name: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        for name in record.names:
            by_name.setdefault(name, []).append(index)
    for indices in by_name.values():
        members: list[tuple[int, shapely.Geometry]] = []
        for index in indices:
            geometry = records[index].geometry
            if geometry is not None and not geometry.is_empty:
                members.append((index, geometry))
        if len(members) < MINIMUM_SPATIAL_GEOMETRIES:
            continue
        for left, right in nearby_pairs(
            [geometry for _index, geometry in members],
            tolerance_degrees=FIRE_PROXIMITY_TOLERANCE_DEGREES,
        ):
            if left != right:
                union(members[left][0], members[right][0])


def fire_complexes(
    memberships: list[peri_scribe.models.ComplexMembership],
    fires_by_identifier: dict[str, peri_scribe.models.Fire],
) -> list[peri_scribe.models.FireComplex]:
    """Build the complexes named by *memberships*, linking their member fires.

    Each complex is linked to every fire it contains, and each linked fire points back
    at the complex. Memberships that reference an unidentified fire are skipped with a
    warning.

    Args:
        memberships: The observed complex memberships.
        fires_by_identifier: The identified fires, keyed by every identifier
            each fire is known by.

    Returns:
        The complexes, in the order first encountered.
    """
    fires_by_complex: dict[str, set[peri_scribe.models.Fire]] = {}
    names_by_complex: dict[str, str] = {}
    for membership in memberships:
        fire = fires_by_identifier.get(membership.fire_identifier)
        if fire is None:
            logger.warning(
                "Complex membership references an unidentified fire",
                fire_identifier=membership.fire_identifier,
                complex_identifier=membership.complex_identifier,
            )
            continue
        fires_by_complex.setdefault(
            membership.complex_identifier,
            set(),
        ).add(fire)
        names_by_complex.setdefault(
            membership.complex_identifier,
            membership.complex_name,
        )
    return [
        peri_scribe.models.FireComplex(
            name=names_by_complex[complex_identifier],
            identifier=complex_identifier,
            fires=frozenset(fires_by_complex[complex_identifier]),
        )
        for complex_identifier in fires_by_complex
    ]


def is_mixed_case(name: str) -> bool:
    """Return whether *name* contains both uppercase and lowercase letters.

    Args:
        name: The name to check.

    Returns:
        True when the name contains both uppercase and lowercase letters.
    """
    return name.lower() != name and name.upper() != name


def most_common_fire(
    occurrences: list[peri_scribe.models.FireRecord],
) -> peri_scribe.models.Fire:
    """Reduce repeated records of the same fire to a single fire.

    The most common mixed case spelling of the name is kept, or the most common spelling
    when none is mixed case. Ties are broken by the first spelling encountered. The fire
    is active when any of its records is active. The canonical identifier prefers a
    unique fire identifier over a GUID, and every identifier is kept as an alias.

    Args:
        occurrences: The records of a single fire.

    Returns:
        The fire with its preferred name spelling, canonical identifier, every alias,
        and aggregated status.
    """
    name_counts = collections.Counter(
        record.name for record in occurrences if is_mixed_case(record.name)
    )
    if not name_counts:
        name_counts = collections.Counter(record.name for record in occurrences)
    most_common_name = name_counts.most_common(1)[0][0]
    identifiers = frozenset(
        identifier
        for record in occurrences
        for identifier in record.identifiers
    )
    status = (
        peri_scribe.models.FireStatus.ACTIVE
        if any(
            record.status is peri_scribe.models.FireStatus.ACTIVE
            for record in occurrences
        )
        else peri_scribe.models.FireStatus.INACTIVE
    )
    return peri_scribe.models.Fire(
        name=most_common_name,
        status=status,
        identifier=peri_scribe.models.canonical_fire_identifier(identifiers),
        aliases=identifiers,
    )
