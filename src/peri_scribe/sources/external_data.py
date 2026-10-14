"""Source definitions and paths shared by collectors and converters.

Design notes:
[External source refresh](../../../docs/algorithms/external-source-refresh.md).
[Source interpretation and validation](../../../docs/algorithms/source-validation.md).
"""

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
    CITIES = "cities"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExternalSource:
    """One external dataset and how to retrieve it.

    An ``arcgis`` source writes to the GeoPackage layer named by ``layer_name``. Its
    optional ``where`` clause restricts which features are queried.

    A ``download`` source supplies a zip archive for conversion to a GeoPackage. With
    ``states``, one archive is fetched per state. Its URL comes from substituting
    ``{state}`` in ``url``, unless ``state_urls`` supplies a mapping from a page's
    "Download links" table. In that case, ``url`` identifies the page, which is read
    when a download is needed so changed links are picked up.

    ``geodata_suffix`` identifies the vector file inside the archive, or a file
    geodatabase directory for ``.gdb``. ``combine`` joins state results into one
    GeoPackage named for the source and removes the state files. ``centroids`` keeps
    each feature's centroid instead of its original geometry, and ``keep_attributes``
    controls whether attribute columns are retained. These options let a source keep
    only the locations needed by the pipeline.

    ``cities`` sources have their own conditional downloader and SQLite database of
    named points. ``compact_database`` selects the dedicated buildings converter and its
    SQLite output at ``sources/{name}.sqlite``. That database has no named layers, so
    ``layer_name`` is optional and the other conversion options do not apply.
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
    # Streaming feeds incoming archive bytes to ``stream_unzip`` and reduces each
    # footprint to its centroid, avoiding archive and GeoJSON files on disk. This option
    # applies only to a ``download`` source with GeoJSON in a zip archive, combined into
    # one GeoPackage of centroids with no attributes.
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
    suffix, as does the dedicated cities source; every other source stores a GeoPackage.

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
    suffix = (
        ".sqlite"
        if source.compact_database or source.kind is ExternalSourceKind.CITIES
        else ".gpkg"
    )
    if state is not None:
        return (
            external_source_directory_path(year_directory, source) / f"{state}{suffix}"
        )
    return (
        peri_scribe.sources.snapshots.sources_directory_path(year_directory)
        / f"{source.name}{suffix}"
    )
