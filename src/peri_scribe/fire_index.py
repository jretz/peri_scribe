"""Building and reading the fire source index for a year's data."""

from __future__ import annotations

import pathlib

import peri_scribe.classification
import peri_scribe.fire_sources
import peri_scribe.models
import peri_scribe.output
import peri_scribe.snapshots


# The current version of the fire source index format; bump it when the format
# changes so that consumers can tell which format a file uses.
FIRE_INDEX_VERSION = "2026-08-18"


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
    classification: peri_scribe.models.FireClassification | None = None,
) -> dict[str, object]:
    """Return a JSON-serializable document for *source*.

    The document has all of the fire's attributes plus the paths of the GeoPackage files
    that mention it, relative to *sources_directory* and sorted by path, and the fire's
    border classification when one is known.

    Args:
        source: The fire and its source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.
        classification: The fire's border classification, or None.

    Returns:
        The fire and its source paths as a JSON-serializable dictionary.
    """
    document: dict[str, object] = {
        **fire_document(source.fire),
        "paths": sorted(
            str(path.relative_to(sources_directory)) for path in source.paths
        ),
    }
    if classification is not None:
        document["classification"] = classification.model_dump(mode="json")
    return document


def fire_index_entries(
    sources: list[peri_scribe.models.FireSources],
    sources_directory: pathlib.Path,
    classifications: dict[
        int,
        peri_scribe.models.FireClassification,
    ]
    | None = None,
) -> list[dict[str, object]]:
    """Return the fire index documents for *sources*, sorted by fire name.

    Args:
        sources: The fires and their source files.
        sources_directory: The directory that holds the index file, used to make the
            GeoPackage paths relative.
        classifications: Each fire's border classification, keyed by the fire object's
            identity, or None when no classifications are known.

    Returns:
        One document per fire, sorted by fire name.
    """
    if classifications is None:
        classifications = {}
    return [
        fire_sources_document(
            source,
            sources_directory,
            classifications.get(id(source.fire)),
        )
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
    ``{year_directory}/sources``, along with the GeoPackage files that mention each fire
    and each fire's border classification when the administrative boundary data is
    available. It is written to ``{year_directory}/sources/fires.json``.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.
    """
    sources_directory = peri_scribe.snapshots.sources_directory_path(year_directory)
    record_groups = peri_scribe.fire_sources.fire_record_groups(sources_directory)
    classifications = peri_scribe.classification.classify_fire_sources(
        record_groups,
        year_directory.parent.parent,
    )
    index = fire_index_document(
        fire_index_entries(
            peri_scribe.fire_sources.fire_sources_from_groups(record_groups),
            sources_directory,
            classifications=classifications,
        ),
    )
    output_path = peri_scribe.snapshots.fire_index_path(year_directory)
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
    index_path = peri_scribe.snapshots.fire_index_path(year_directory)
    if not index_path.is_file():
        index_fire_sources(year_directory)
    return peri_scribe.models.FireIndex.model_validate_json(
        index_path.read_text(encoding="utf-8"),
    )
