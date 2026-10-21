"""Build payload-free source-index evidence beside its complete source contents."""

from __future__ import annotations

import pathlib

import peri_scribe.fires.source_index_cache
import peri_scribe.fires.sources
import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.geo.source_summaries
import peri_scribe.models
import spatial_data.geometry_pool


def read(
    directory: pathlib.Path,
    contents: dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents],
) -> peri_scribe.fires.source_index_cache.IndexRead:
    """Project explicit full source contents with exact component identities.

    Args:
        directory: The provenance root containing the supplied snapshots.
        contents: Complete ordered evidence for every supplied source path.

    Returns:
        Slim evidence retaining its full contents for selected hydration.
    """
    return peri_scribe.fires.source_index_cache.index_read(
        directory,
        {
            path: peri_scribe.geo.source_summaries.summarize(path, value)
            for path, value in contents.items()
        },
        contents,
        spatial_data.geometry_pool.GeometryPool(),
    )


def complex_sources(
    directory: pathlib.Path,
) -> tuple[
    peri_scribe.fires.sources.PreparedSources,
    dict[pathlib.Path, peri_scribe.geo.package.GeopackageContents],
]:
    """Keep current complex declarations and aliases beside real byte identities.

    Args:
        directory: Isolated source root for a declared test parse.

    Returns:
        Complete grouped preparation and the declared parses for two snapshots.
    """
    paths = [
        directory / "feed/000___" / f"{index:06d},lastEdit=0.gpkg" for index in range(2)
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    child = peri_scribe.geo.package.FireRowRecord(
        record=peri_scribe.models.FireRecord(
            name="Canyon",
            names=frozenset({"canyon"}),
            identifiers=frozenset({"child"}),
            status=peri_scribe.models.FireStatus.ACTIVE,
        ),
        object_id=1,
        source_name="feed",
        attributes={
            "IsCpxChild": True,
            "CpxID": "parent",
            "CpxName": "Complex",
        },
    )
    parent = peri_scribe.geo.package.FireRowRecord(
        record=peri_scribe.models.FireRecord(
            name="Complex",
            names=frozenset({"complex"}),
            identifiers=frozenset({"parent"}),
            status=peri_scribe.models.FireStatus.ACTIVE,
        ),
        object_id=2,
        source_name="feed",
        attributes={},
    )
    membership = peri_scribe.models.ComplexMembership(
        fire_identifier="child",
        complex_identifier="parent",
        complex_name="Complex",
    )
    contents = {
        paths[0]: peri_scribe.geo.package.GeopackageContents(
            rows=(child, parent),
            memberships=(),
        ),
        paths[1]: peri_scribe.geo.package.GeopackageContents(
            rows=(child,),
            memberships=(membership,),
        ),
    }
    source = peri_scribe.fires.sources.ReadFireSources(
        rows=(child, parent, child),
        paths=(paths[0], paths[0], paths[1]),
        memberships=(membership,),
        membership_paths=(paths[1],),
        source_checksums=tuple(
            (path, peri_scribe.geo.database.snapshot_checksum(path)) for path in paths
        ),
    )
    return peri_scribe.fires.sources.PreparedSources(
        read=source,
        groups=peri_scribe.fires.sources.group_fire_sources(source),
    ), contents
