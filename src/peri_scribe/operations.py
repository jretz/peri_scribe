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

# When fetching only changed features, the cutoff for the query is moved back by
# this amount so that recently edited features are re-fetched and re-checked rather
# than missed because of clock skew or in-flight edits.
OVERLAP = datetime.timedelta(minutes=5)


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
        base_dir
        / DATA_DIRECTORY_NAME
        / str(year)
        / SOURCES_DIRECTORY_NAME
        / source_name
        / geopackage_filename(serial_number, watermark)
    )


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
        The parsed UTC datetime, or None when *value* is blank or unparseable.
    """
    if value is None:
        return None
    try:
        if pd.isna(value) and not isinstance(value, (str, bytes)):
            return None
    except TypeError, ValueError:
        pass

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
    return max((value for value in values if value is not None), default=None)


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
    if value is None:
        return None
    try:
        if pd.isna(value) and not isinstance(value, (str, bytes)):
            return None
    except TypeError, ValueError:
        pass
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
        attributes = tuple(
            normalized_attribute_value(values[column]) for column in columns
        )
        geometry = values[geometry_name]
        geometry_key = geometry.wkb if geometry is not None else None
        signatures[object_id] = (attributes, geometry_key)
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
        geometry = values[geometry_name]
        signature = (
            tuple(normalized_attribute_value(values[column]) for column in columns),
            geometry.wkb if geometry is not None else None,
        )
        keep.append(existing_signatures.get(object_id) != signature)
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

    Args:
        base_dir: Directory under which the ``data`` directory tree is created.
            Defaults to the current working directory.
        year: Year to group the snapshots under. Defaults to the current year.

    Returns:
        The paths to the GeoPackage files holding each feed's data, one per feed, in
        feed order. A feed that produced no new snapshot contributes its most recent
        existing snapshot path instead.

    Raises:
        SystemExit: If a feed is unreachable, returns no features, cannot observe a
            watermark, or lacks a modified column for an incremental fetch.
    """
    if base_dir is None:
        base_dir = pathlib.Path.cwd()
    if year is None:
        year = datetime.date.today().year
    gis = arcgis.gis.GIS()
    snapshot_paths: list[pathlib.Path] = []
    for feed in peri_scribe.models.FEEDS:
        logger.info("Fetching", feed=feed.name, url=feed.url)
        watermark = feed.current_watermark
        if watermark is None:
            message = f"Failed to fetch {feed.name}: no watermark could be observed"
            raise SystemExit(message)
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
            layer = arcgis.features.FeatureLayer(feed.url, gis)
            geodataframe = fetch_feed_dataframe(
                feed,
                layer,
                existing_filenames,
                source_directory,
            )
        except Exception as error:
            # Fail fast with a readable message if a feed is unreachable.
            message = f"Failed to fetch {feed.name}: {error}"
            raise SystemExit(message) from error
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
    logger.info("Done")
    return tuple(snapshot_paths)


def list_fires(directory: pathlib.Path) -> list[peri_scribe.models.Fire]:
    """Collect the fires in the GeoPackage files under *directory*.

    Every GeoPackage file anywhere below *directory* is read, so snapshots stored under
    ``sources/{feed}/{serial}.gpkg`` are all found. Fire records are identified by their
    stable identifier when they have one, falling back to a normalized name only when a
    record has no identifier, so that different fires that happen to share a name are
    not merged (e.g. "Canyon" in California vs. Alaska). The most common spelling of
    each name is the one kept, and a fire is active when any of its records is active.
    Fires that are complex parents are represented by a FireComplex instead of listed as
    fires, and member fires carry a circular link to their complex.

    Args:
        directory: The directory tree holding GeoPackage files with fire data.

    Returns:
        The fires, in the order first encountered.

    Raises:
        SystemExit: If a GeoPackage file cannot be read.
        UnknownLayerError: If a layer does not correspond to a configured feed.
    """
    records: list[peri_scribe.models.Fire] = []
    memberships: list[peri_scribe.models.ComplexMembership] = []
    for path in geo_package_files(directory):
        try:
            records.extend(peri_scribe.geo_data.fire_names(path))
            memberships.extend(peri_scribe.geo_data.complex_memberships(path))
        except peri_scribe.exceptions.UnknownLayerError:
            raise
        except Exception as error:
            # Fail fast with a readable message if a GeoPackage is unreadable.
            message = f"Failed to read {path}: {error}"
            raise SystemExit(message) from error
    groups = group_fire_records(records)
    fires = [most_common_fire(group) for group in groups]
    fires_by_identifier: dict[str, peri_scribe.models.Fire] = {}
    for group, fire in zip(groups, fires, strict=True):
        for record in group:
            if record.identifier is not None:
                fires_by_identifier.setdefault(record.identifier, fire)
    complexes = fire_complexes(memberships, fires_by_identifier)
    complex_identifiers = {complex_.identifier for complex_ in complexes}
    return [
        fire
        for fire, group in zip(fires, groups, strict=True)
        if not any(record.identifier in complex_identifiers for record in group)
    ]


def normalize_fire_name(name: str) -> str:
    """Normalize a fire name for comparison.

    Names are casefolded, stripped of surrounding whitespace, and internal whitespace
    runs are collapsed to a single space.

    Args:
        name: The fire name to normalize.

    Returns:
        The normalized name.
    """
    return " ".join(name.casefold().split())


def group_fire_records(
    records: list[peri_scribe.models.Fire],
) -> list[list[peri_scribe.models.Fire]]:
    """Group fire records that identify the same fire into a single list.

    Records with the same normalized identifier are the same fire, even when their names
    differ (e.g. "Crosswhite" and "0445 CROSSWHITE"). Records with the same normalized
    name are the same fire only when at least one of them has no identifier, since names
    alone are unreliable: different fires can share a name (e.g. "Canyon" in California
    vs. Alaska), and the same fire can appear with and without an identifier (e.g.
    California FIRIS records vs. WFIGS records for the same fire).

    Args:
        records: The fire records to group.

    Returns:
        The groups of records, in the order first encountered.
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

    by_identifier: dict[str, int] = {}
    by_name: dict[str, int] = {}
    by_unidentified_name: dict[str, int] = {}
    for index, fire in enumerate(records):
        name = normalize_fire_name(fire.name)
        by_name.setdefault(name, index)
        if fire.identifier is not None:
            if fire.identifier in by_identifier:
                union(index, by_identifier[fire.identifier])
            else:
                by_identifier[fire.identifier] = index
            if name in by_unidentified_name:
                union(index, by_unidentified_name[name])
        else:
            if name in by_unidentified_name:
                union(index, by_unidentified_name[name])
            else:
                by_unidentified_name[name] = index
            union(index, by_name[name])
    groups_by_root: dict[int, list[peri_scribe.models.Fire]] = {}
    order: list[int] = []
    for index, fire in enumerate(records):
        root = find(index)
        if root not in groups_by_root:
            order.append(root)
            groups_by_root[root] = []
        groups_by_root[root].append(fire)
    return [groups_by_root[root] for root in order]


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
    occurrences: list[peri_scribe.models.Fire],
) -> peri_scribe.models.Fire:
    """Reduce repeated records of the same fire to a single fire.

    The most common mixed case spelling of the name is kept, or the most common spelling
    when none is mixed case. Ties are broken by the first spelling encountered. The fire
    is active when any of its records is active.

    Args:
        occurrences: The records of a single fire, deduplicated by case-folded
            name.

    Returns:
        The fire with its preferred name spelling, its first identifier, and
        aggregated status.
    """
    name_counts = collections.Counter(
        fire.name for fire in occurrences if is_mixed_case(fire.name)
    )
    if not name_counts:
        name_counts = collections.Counter(fire.name for fire in occurrences)
    most_common_name = name_counts.most_common(1)[0][0]
    identifier = next(
        (fire.identifier for fire in occurrences if fire.identifier is not None),
        None,
    )
    status = (
        peri_scribe.models.FireStatus.ACTIVE
        if any(
            fire.status is peri_scribe.models.FireStatus.ACTIVE for fire in occurrences
        )
        else peri_scribe.models.FireStatus.INACTIVE
    )
    return peri_scribe.models.Fire(
        name=most_common_name,
        status=status,
        identifier=identifier,
    )
