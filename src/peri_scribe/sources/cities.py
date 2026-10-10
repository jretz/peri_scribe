"""Keep Natural Earth's eligible US places in a validated local SQLite database.

Design notes:
[External source refresh](../../../docs/algorithms/external-source-refresh.md).
[Nearest place descriptions](../../../docs/algorithms/nearest-place.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import json
import pathlib
import sqlite3
import typing
import zipfile

import geopandas
import pydantic
import requests
import structlog
import us

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import peri_scribe.sources.downloading
import peri_scribe.sources.external_data
import peri_scribe.sources.network
import spatial_data.reference


logger = structlog.get_logger()
SCHEMA_VERSION = 1
ARCHIVE_STEM = "ne_10m_populated_places_simple"
STATE_ABBREVIATIONS = {
    state.name: state.abbr for state in (*us.states.STATES, us.states.DC)
}
TERRITORY_ABBREVIATIONS = {
    "ASM": "AS",
    "GUM": "GU",
    "MNP": "MP",
    "PRI": "PR",
    "UMI": "UM",
    "VIR": "VI",
}
STATE_CODES = frozenset([
    *STATE_ABBREVIATIONS.values(),
    *TERRITORY_ABBREVIATIONS.values(),
])


class City(pydantic.BaseModel):
    """Reject malformed source coordinates before they can authorize cache reuse."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid", strict=True)
    name: str = pydantic.Field(min_length=1)
    state: str = pydantic.Field(pattern=r"^[A-Z]{2}$")
    longitude: float = pydantic.Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = pydantic.Field(ge=-90, le=90, allow_inf_nan=False)


class Metadata(pydantic.BaseModel):
    """Publish HTTP validators together with the exact data they authenticate."""

    model_config = pydantic.ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: typing.Literal[1]
    source_url: str
    source_version: str = pydantic.Field(pattern=r"^\d+\.\d+\.\d+$")
    archive_sha256: str = pydantic.Field(pattern=r"^[0-9a-f]{64}$")
    contents_sha256: str = pydantic.Field(pattern=r"^[0-9a-f]{64}$")
    etag: str | None
    last_modified: str | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Database:
    """Keep validated locations and their retrieval evidence in one generation."""

    cities: tuple[City, ...]
    metadata: Metadata


def city_database_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Locate the cities alongside the year's other external sources.

    Args:
        year_directory: The year whose source data is being used.

    Returns:
        The published cities SQLite path.
    """
    return peri_scribe.sources.external_data.output_path(
        year_directory,
        peri_scribe.sources.catalog.CITIES_SOURCE,
    )


def contents_digest(cities: tuple[City, ...]) -> str:
    """Make publication depend on location content rather than download metadata.

    Args:
        cities: Validated operational records; input ordering is insignificant.

    Returns:
        The SHA-256 digest of the four retained fields, including duplicate rows.
    """
    records = sorted(
        (city.name, city.state, city.longitude, city.latitude) for city in cities
    )
    return hashlib.sha256(json.dumps(records, ensure_ascii=False).encode()).hexdigest()


def validate_cities(cities: tuple[City, ...]) -> None:
    """Require usable US place names and postal states in every published row.

    Args:
        cities: Coordinate-validated records from a source archive or database.

    Raises:
        ValueError: If no places remain or a name or state cannot be displayed.
    """
    if not cities or any(
        not city.name.strip() or city.state not in STATE_CODES for city in cities
    ):
        message = "Cities must contain nonempty place names and valid US state codes"
        raise ValueError(message)


def load_database(path: pathlib.Path, source_url: str) -> Database:
    """Validate stored contents before trusting their validators or publication digest.

    Args:
        path: A database to inspect without creating or changing it.
        source_url: The configured download whose cache is eligible for reuse.

    Returns:
        The completely validated generation.

    Raises:
        ValueError: If metadata, operational rows, or their checksum are invalid.
    """
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True),
    ) as connection:
        connection.execute("BEGIN")
        metadata_rows = connection.execute("SELECT document FROM metadata").fetchall()
        if len(metadata_rows) != 1:
            message = "Cities database requires exactly one metadata record"
            raise ValueError(message)
        metadata = Metadata.model_validate_json(metadata_rows[0][0])
        cities = tuple(
            City(name=name, state=state, longitude=longitude, latitude=latitude)
            for name, state, longitude, latitude in connection.execute(
                "SELECT name, state, longitude, latitude FROM cities",
            )
        )
    validate_cities(cities)
    if metadata.source_url != source_url or metadata.contents_sha256 != contents_digest(
        cities,
    ):
        message = "Cities database source or contents checksum does not match"
        raise ValueError(message)
    return Database(cities=cities, metadata=metadata)


def read_database(path: pathlib.Path, source_url: str) -> Database | None:
    """Treat absent or damaged caches as requiring a complete fresh download.

    Args:
        path: The published database to inspect.
        source_url: The configured source URL expected in its metadata.

    Returns:
        Validated data, or None when no usable cached generation exists.
    """
    if not path.is_file():
        return None
    try:
        return load_database(path, source_url)
    except OSError, sqlite3.Error, ValueError:
        logger.warning("Cities database is unusable", path=str(path), exc_info=True)
        return None


def database_digest(year_directory: pathlib.Path) -> str | None:
    """Expose only authenticated place content to publication change detection.

    Args:
        year_directory: The year whose locations are publication inputs.

    Returns:
        The content digest, or None when a usable source is unavailable.
    """
    database = read_database(
        city_database_path(year_directory),
        peri_scribe.sources.catalog.CITIES_SOURCE.url,
    )
    return database.metadata.contents_sha256 if database is not None else None


def read_cities(year_directory: pathlib.Path) -> geopandas.GeoDataFrame:
    """Supply report locations without requiring a network request during rendering.

    Args:
        year_directory: The year whose current cities should describe fires.

    Returns:
        Names, postal states, and WGS84 point geometry; empty if no cache is usable.
    """
    database = read_database(
        city_database_path(year_directory),
        peri_scribe.sources.catalog.CITIES_SOURCE.url,
    )
    cities = database.cities if database is not None else ()
    return geopandas.GeoDataFrame(
        {
            "NAME": [city.name for city in cities],
            "STATE_ABBR": [city.state for city in cities],
        },
        geometry=geopandas.points_from_xy(
            [city.longitude for city in cities],
            [city.latitude for city in cities],
        ),
        crs=spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
    )


def conditional_headers(database: Database | None) -> dict[str, str]:
    """Prefer ETags and use modification time only when no ETag is available.

    Args:
        database: The validated generation supplying its matching HTTP validators.

    Returns:
        A conditional header, or none when the request must download a complete copy.
    """
    if database is None:
        return {}
    if database.metadata.etag:
        return {"If-None-Match": database.metadata.etag}
    if database.metadata.last_modified:
        return {"If-Modified-Since": database.metadata.last_modified}
    return {}


def archive_cities(content: bytes) -> tuple[str, tuple[City, ...]]:
    """Retain every US and territorial place, taking coordinates from point geometry.

    Args:
        content: A complete Natural Earth populated-places-simple archive.

    Returns:
        The source version and validated four-field records.

    Raises:
        ValueError: If source rows cannot be safely used as named geographic points.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        version = archive.read(f"{ARCHIVE_STEM}.VERSION.txt").decode().strip()
    dataframe = geopandas.read_file(io.BytesIO(content))
    selected = dataframe[dataframe["sov_a3"] == "USA"].to_crs(
        spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
    )
    if (
        not (selected.geometry.geom_type == "Point").all()
        or selected.geometry.is_empty.any()
    ):
        message = "Natural Earth cities require nonempty point geometries"
        raise ValueError(message)
    cities = tuple(
        City(
            name=row.name,
            state=(
                STATE_ABBREVIATIONS[row.adm1name]
                if row.adm0_a3 == "USA"
                else TERRITORY_ABBREVIATIONS[row.adm0_a3]
            ),
            longitude=row.geometry.x,
            latitude=row.geometry.y,
        )
        for row in selected.itertuples(index=False)
    )
    validate_cities(cities)
    return version, cities


def write_database(path: pathlib.Path, database: Database) -> None:
    """Write one complete generation to an unpublished staging path.

    Args:
        path: A new staging file on the published database's filesystem.
        database: Validated location records and their download metadata.
    """
    with contextlib.closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE cities (name TEXT NOT NULL, state TEXT NOT NULL, "
            "longitude REAL NOT NULL, latitude REAL NOT NULL) STRICT",
        )
        connection.execute("CREATE TABLE metadata (document TEXT NOT NULL) STRICT")
        connection.executemany(
            "INSERT INTO cities VALUES (?, ?, ?, ?)",
            (
                (city.name, city.state, city.longitude, city.latitude)
                for city in database.cities
            ),
        )
        connection.execute(
            "INSERT INTO metadata VALUES (?)",
            (database.metadata.model_dump_json(),),
        )


def publish_database(path: pathlib.Path, database: Database) -> None:
    """Make a replacement visible only after its complete stored contents validate.

    Args:
        path: The published database, preserved if staging or validation fails.
        database: The new complete generation.

    Raises:
        ValueError: If staging does not preserve the validated generation.
    """
    with peri_scribe.sources.downloading.completed_download(path) as temporary:
        write_database(temporary, database)
        if load_database(temporary, database.metadata.source_url) != database:
            message = "Staged cities database does not match its validated source"
            raise ValueError(message)


def refresh_database(
    source: peri_scribe.sources.external_data.ExternalSource,
    path: pathlib.Path,
    previous: Database | None,
) -> None:
    """Check the provider on every fetch while reusing a validated unchanged copy.

    Args:
        source: The configured Natural Earth download.
        path: The destination database.
        previous: The usable generation eligible for conditional requests.

    Raises:
        ValueError: If a response cannot supply or authorize usable source data.
    """
    with requests.get(
        source.url,
        headers=conditional_headers(previous),
        timeout=peri_scribe.sources.network.REQUEST_TIMEOUT_SECONDS,
    ) as response:
        response.raise_for_status()
        if response.status_code == requests.codes.not_modified:
            if previous is None:
                message = "Natural Earth returned 304 without a usable cities database"
                raise ValueError(message)
            return
        if response.status_code != requests.codes.ok:
            message = f"Unexpected Natural Earth HTTP status {response.status_code}"
            raise ValueError(message)
        content = response.content
        version, cities = archive_cities(content)
        database = Database(
            cities=cities,
            metadata=Metadata(
                schema_version=SCHEMA_VERSION,
                source_url=source.url,
                source_version=version,
                archive_sha256=hashlib.sha256(content).hexdigest(),
                contents_sha256=contents_digest(cities),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            ),
        )
    publish_database(path, database)


def fetch_cities_database(
    source: peri_scribe.sources.external_data.ExternalSource,
    year_directory: pathlib.Path,
) -> tuple[pathlib.Path, ...]:
    """Keep usable cached locations on refresh failure and fail when none exist.

    Args:
        source: The configured Natural Earth populated-place source.
        year_directory: The year owning the downloaded source.

    Returns:
        The sole usable cities database path.

    Raises:
        ExternalDataError: If fetching fails without a usable cached generation.
    """
    path = peri_scribe.sources.external_data.output_path(year_directory, source)
    previous = read_database(path, source.url)
    try:
        refresh_database(source, path, previous)
    except Exception as error:
        if previous is not None:
            logger.warning(
                "Failed to fetch cities; keeping current data",
                source=source.name,
                error=str(error),
                exc_info=True,
            )
        else:
            logger.exception(
                "Failed to fetch cities without usable cached data",
                source=source.name,
                error=str(error),
            )
            message = f"Failed to fetch cities without usable cached data: {error}"
            raise peri_scribe.exceptions.ExternalDataError(message) from error
    return (path,)
