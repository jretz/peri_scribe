"""Find the feature IDs whose full records need an incremental source query.

Design notes:
[Incremental source collection](../../../docs/algorithms/source-collection.md).
"""

from __future__ import annotations

import typing

import structlog

import arcgis_access.data
import peri_scribe.models
import peri_scribe.sources.changes
import peri_scribe.sources.feed_state
import peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import arcgis.features
    import geopandas


logger = structlog.get_logger()


def object_ids(
    feed: peri_scribe.sources.feed_types.Feed,
    layer: arcgis.features.FeatureLayer,
    change_columns: tuple[str, ...],
    existing: geopandas.GeoDataFrame | None,
) -> list[int]:
    """Combine timestamp, unseen-ID, and status-change queries for one feed.

    Args:
        feed: The configured source whose existing rows are being refreshed.
        layer: The ArcGIS feature layer to query for candidates.
        change_columns: The source's nonempty set of change timestamp fields.
        existing: The latest retained rows before this refresh.

    Returns:
        Sorted distinct feature identifiers to query for their full contents.
    """
    cutoff = peri_scribe.sources.changes.incremental_cutoff(existing, feed)
    where = peri_scribe.sources.feed_state.where_clause_for(change_columns, cutoff)
    changed_ids = arcgis_access.data.query_object_ids_with_retry(
        feed.name,
        layer,
        where=where,
    )
    # A source may publish features without updating their modified timestamps, so the
    # timestamp query alone can miss features that are present in the layer but never
    # stored (for example a WFIGS row re-added with an outdated modified time). Compare
    # the layer's full OBJECTID set against the stored set to catch them.
    stored_ids = peri_scribe.sources.feed_state.stored_object_ids(existing)
    layer_ids = set(
        arcgis_access.data.query_object_ids_with_retry(feed.name, layer, where="1=1"),
    )
    missing_ids = sorted(layer_ids - stored_ids)
    if missing_ids:
        logger.debug(
            "Found features present but not stored",
            feed=feed.name,
            count=len(missing_ids),
        )
    active_ids = peri_scribe.sources.feed_state.stored_status_object_ids(
        existing,
        feed,
        peri_scribe.models.FireStatus.ACTIVE,
    )
    inactive_literals = peri_scribe.sources.feed_state.stored_status_literals(
        existing,
        feed,
        peri_scribe.models.FireStatus.INACTIVE,
    )
    flipped_ids: list[int] = []
    if active_ids and inactive_literals:
        # A source may flip a stored feature's status to inactive without updating its
        # modified timestamp, so re-check the stored-active features' statuses.
        flipped_ids = arcgis_access.data.query_object_ids_with_retry(
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
    return sorted(set(changed_ids) | set(missing_ids) | set(flipped_ids))
