"""Source definitions and paths shared by collectors and converters."""

from __future__ import annotations

import dataclasses
import enum
import typing

import peri_scribe.sources.snapshots


if typing.TYPE_CHECKING:
    import collections.abc
    import pathlib


class ExternalSourceKind(enum.Enum):
    """How an external source is retrieved."""

    ARCGIS = "arcgis"
    DOWNLOAD = "download"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExternalSource:
    """One external dataset and how to retrieve it.

    For an ``arcgis`` source, ``layer_name`` names the GeoPackage layer the features are
    written to and ``where`` optionally restricts the query. For a ``download`` source,
    ``url`` points at a zip archive that is downloaded, extracted, and converted to a
    GeoPackage. When ``states`` is non-empty the URL is a format template containing
    ``{state}`` and one archive is fetched per state, unless ``state_urls`` is set: then
    ``url`` names the page whose "Download links" table maps each state to its archive
    URL, and that page is loaded only when an archive is actually downloaded, so the
    links are always current. When ``combine`` is true the per-state results are
    concatenated into a single GeoPackage named for the source, and the per-state files
    are removed. When ``centroids`` is true the converted GeoPackage holds each
    feature's centroid point instead of its original geometry, and ``geodata_suffix``
    names the file (or file geodatabase directory, for a ``.gdb`` archive) inside the
    extracted archive that holds the vector data. When ``keep_attributes`` is false the
    converted GeoPackage holds only the geometry, dropping every attribute column. When
    ``compact_database`` is true the source's output is the compact buildings SQLite
    database (``sources/{name}.sqlite``), produced and read by the dedicated buildings
    converter rather than the generic GeoPackage conversion paths; the database holds no
    named layers, so ``layer_name`` is not required, and the other conversion options do
    not apply.
    """

    name: str
    kind: ExternalSourceKind
    url: str
    layer_name: str | None = None
    where: str | None = None
    states: tuple[str, ...] = ()
    # When true, the source's output is the compact buildings SQLite database, built and
    # read by the dedicated buildings converter rather than the generic GeoPackage
    # conversion paths.
    compact_database: bool = False
    # When true, the per-state results are concatenated into a single GeoPackage named
    # for the source and the per-state files are removed.
    combine: bool = False
    # When true, the source's archive is streamed and converted without ever writing the
    # archive or its GeoJSON to disk: the archive's bytes feed ``stream_unzip`` while
    # they arrive and each footprint is reduced to its centroid point. Only meaningful
    # for a ``download`` source whose archive is a zip holding a GeoJSON member,
    # combined into one GeoPackage, and reduced to centroids with no attributes.
    stream: bool = False
    centroids: bool = False
    keep_attributes: bool = True
    geodata_suffix: str = ".geojson"
    # A callable returning the mapping from state name to archive URL, read from the
    # source's page when an archive is downloaded. When set, ``url`` names the page
    # holding the "Download links" table and is not a download URL itself.
    state_urls: collections.abc.Callable[[], dict[str, str]] | None = None


def external_source_directory_path(
    year_directory: pathlib.Path,
    source: ExternalSource,
) -> pathlib.Path:
    """Return the directory that holds *source*'s retrieved data.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The external source.

    Returns:
        The source's directory under the year's sources directory.
    """
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / source.name
    )


def output_path(
    year_directory: pathlib.Path,
    source: ExternalSource,
    *,
    state: str | None = None,
) -> pathlib.Path:
    """Return the path where *source*'s database is stored.

    A source that produces a single file stores it directly under the sources directory,
    named for the source (or, for a live ArcGIS source, at that same fixed path holding
    its latest version). A per-state download source produces one file per state, so its
    files stay under the source's own directory. A compact source uses the ``.sqlite``
    suffix; every other source stores a GeoPackage.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
        source: The external source.
        state: The state, for a per-state source.

    Returns:
        The path to the source's database.

    Raises:
        ValueError: If *source* is a combined source and *state* is given.
    """
    if source.combine and state is not None:
        message = f"Source {source.name} combines its states into one database"
        raise ValueError(message)
    suffix = ".sqlite" if source.compact_database else ".gpkg"
    if state is not None:
        return (
            external_source_directory_path(year_directory, source) / f"{state}{suffix}"
        )
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / f"{source.name}{suffix}"
    )
