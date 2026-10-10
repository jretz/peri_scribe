"""Construct compact Natural Earth downloads and authenticated city generations."""

from __future__ import annotations

import hashlib
import io
import typing
import zipfile

import shapely.geometry

import peri_scribe.sources.catalog
import peri_scribe.sources.cities
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.sources.external_source


if typing.TYPE_CHECKING:
    import geopandas


def city(
    *,
    name: str = "Bakersfield",
    state: str = "CA",
    longitude: float = -119.0,
    latitude: float = 35.0,
) -> peri_scribe.sources.cities.City:
    """Give focused persistence tests a known source point.

    Args:
        name: The place's display name.
        state: Its postal state or territory.
        longitude: The WGS84 longitude in degrees.
        latitude: The WGS84 latitude in degrees.

    Returns:
        The validated operational record.
    """
    return peri_scribe.sources.cities.City(
        name=name,
        state=state,
        longitude=longitude,
        latitude=latitude,
    )


def database(
    *,
    cities: tuple[peri_scribe.sources.cities.City, ...] | None = None,
    etag: str | None = '"first"',
    last_modified: str | None = None,
) -> peri_scribe.sources.cities.Database:
    """Pair known rows with the metadata needed to authorize reuse.

    Args:
        cities: Operational rows, or one Bakersfield point when omitted.
        etag: The provider's entity tag.
        last_modified: The provider's fallback validator.

    Returns:
        A complete generation ready for a test's temporary SQLite file.
    """
    records = cities if cities is not None else (city(),)
    return peri_scribe.sources.cities.Database(
        cities=records,
        metadata=peri_scribe.sources.cities.Metadata(
            schema_version=peri_scribe.sources.cities.SCHEMA_VERSION,
            source_url=peri_scribe.sources.catalog.CITIES_SOURCE.url,
            source_version="5.1.2",
            archive_sha256=hashlib.sha256(b"test archive").hexdigest(),
            contents_sha256=peri_scribe.sources.cities.contents_digest(records),
            etag=etag,
            last_modified=last_modified,
        ),
    )


def dataframe() -> geopandas.GeoDataFrame:
    """Include a state, DC, each populated territory, and a foreign exclusion.

    Returns:
        Source-shaped points with deliberately different coordinate attributes.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "name": [
                "Bakersfield",
                "Washington",
                "Pago Pago",
                "Agana",
                "Capitol Hill",
                "San Juan",
                "Christiansted",
                "Toronto",
            ],
            "sov_a3": ["USA"] * 7 + ["CAN"],
            "adm0_a3": ["USA", "USA", "ASM", "GUM", "MNP", "PRI", "VIR", "CAN"],
            "adm1name": ["California", "District of Columbia"] + [None] * 6,
            "latitude": [0.0] * 8,
            "longitude": [0.0] * 8,
        },
        [shapely.geometry.Point(-119.0 + index, 35.0) for index in range(8)],
    )


def archive(
    source: geopandas.GeoDataFrame | None = None,
    *,
    version: str = "5.1.2",
) -> bytes:
    """Build a real shapefile ZIP so tests exercise geometry and source fields.

    Args:
        source: The source-shaped frame, or the representative default rows.
        version: The provider's version-file contents.

    Returns:
        A complete in-memory Natural Earth-style ZIP download.
    """
    content = (
        tests.helpers.factories.peri_scribe.sources.external_source.archive_zip_bytes(
            filename=f"{peri_scribe.sources.cities.ARCHIVE_STEM}.shp",
            dataframe=source if source is not None else dataframe(),
            driver="ESRI Shapefile",
        )
    )
    buffer = io.BytesIO(content)
    with zipfile.ZipFile(buffer, "a") as compressed:
        compressed.writestr(
            f"{peri_scribe.sources.cities.ARCHIVE_STEM}.VERSION.txt",
            version,
        )
    return buffer.getvalue()
