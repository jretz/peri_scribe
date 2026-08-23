"""Validating that stored source snapshots cover a complete snapshot."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import peri_scribe.changes
import peri_scribe.feed_types
import peri_scribe.geo_package
import peri_scribe.models
import peri_scribe.snapshots


if typing.TYPE_CHECKING:
    import geopandas
    import shapely


@dataclasses.dataclass(frozen=True, kw_only=True)
class FeedValidationResult:
    """The outcome of validating one feed's stored snapshots.

    The stored snapshots are expected to cover the complete snapshot: every feature
    in the complete snapshot should be present in the stored snapshots with matching
    attributes and geometry, and the stored snapshots should carry every attribute
    column the complete snapshot carries. Stored snapshots may hold additional
    features and columns without being flagged.
    """

    feed_name: str
    complete_feature_count: int
    missing_object_ids: frozenset[int]
    mismatched_object_ids: frozenset[int]
    columns_missing_from_stored: frozenset[str]

    @property
    def has_problems(self) -> bool:
        """Return True when stored snapshots do not fully cover the complete one."""
        return bool(
            self.missing_object_ids
            or self.mismatched_object_ids
            or self.columns_missing_from_stored,
        )


def attribute_columns_of(dataframe: geopandas.GeoDataFrame) -> frozenset[str]:
    """Return the names of *dataframe*'s attribute columns.

    The geometry column and the OBJECTID key column are excluded, so the result is
    the columns whose values can be compared between two snapshots.

    Args:
        dataframe: The features whose attribute columns are returned.

    Returns:
        The attribute column names.
    """
    return frozenset(str(column) for column in dataframe.columns) - {
        str(dataframe.geometry.name),
        peri_scribe.models.OBJECT_ID_COLUMN_NAME,
    }


def feature_contents(
    dataframe: geopandas.GeoDataFrame,
    columns: list[str],
) -> dict[int, tuple[tuple[object, ...], object]]:
    """Return each feature's comparable content, keyed by OBJECTID.

    The content is the feature's normalized attribute values together with its raw
    geometry. Geometries are kept separate from attributes because they are compared
    with topological equality rather than by raw well-known binary: a source may wrap
    identical coordinates in a different geometry type from one query to the next (a
    single-part polygon arrives as either a Polygon or a MultiPolygon), and a raw
    comparison would flag identical features.

    Args:
        dataframe: The features whose content is returned.
        columns: The attribute columns to include in each content record.

    Returns:
        The content records, keyed by OBJECTID.
    """
    geometry_name = dataframe.geometry.name
    contents: dict[int, tuple[tuple[object, ...], object]] = {}
    for row in dataframe.itertuples(index=False, name=None):
        values = dict(zip(dataframe.columns, row, strict=True))
        object_id = int(values[peri_scribe.models.OBJECT_ID_COLUMN_NAME])
        attributes = tuple(
            peri_scribe.changes.normalized_attribute_value(values[column])
            for column in columns
        )
        contents[object_id] = (attributes, values[geometry_name])
    return contents


def geometries_equal(left: object, right: object) -> bool:
    """Return True when two feature geometries cover the same point set.

    The source may wrap identical coordinates in a different geometry type from one
    query to the next, so comparing raw well-known binaries would flag identical
    features. Topological equality treats those wrappers as the same content while
    still catching real changes to the geometry.

    Args:
        left: One feature geometry, or None when the feature has none.
        right: The other feature geometry, or None when the feature has none.

    Returns:
        True when both geometries are missing or cover the same point set.
    """
    if left is None or right is None:
        return left is None and right is None
    return typing.cast("shapely.Geometry", left).equals(
        typing.cast("shapely.Geometry", right),
    )


def feature_contents_equal(
    complete: tuple[tuple[object, ...], object],
    stored: tuple[tuple[object, ...], object],
) -> bool:
    """Return True when two features' attributes and geometry match.

    Attributes are compared after normalization and geometries with topological
    equality, so a feature whose coordinates are identical but wrapped in a different
    geometry type matches.

    Args:
        complete: The complete snapshot's feature content.
        stored: The stored feature content.

    Returns:
        True when the contents match.
    """
    return complete[0] == stored[0] and geometries_equal(complete[1], stored[1])


def validate_feed(
    feed: peri_scribe.feed_types.Feed,
    complete_dataframe: geopandas.GeoDataFrame,
    stored_dataframe: geopandas.GeoDataFrame | None,
) -> FeedValidationResult:
    """Compare one feed's stored snapshots against its complete snapshot.

    A feature is missing when its OBJECTID appears in the complete snapshot but not
    in the stored snapshots, and mismatched when its stored attributes or geometry
    differ from the complete snapshot's. Attribute columns that the complete snapshot
    carries but the stored snapshots lack are reported separately, since a value
    comparison cannot cover them.

    Args:
        feed: The feed both snapshots came from.
        complete_dataframe: The feed's complete snapshot features.
        stored_dataframe: The feed's latest stored feature per OBJECTID, or None when
            the store holds no feature data for the feed.

    Returns:
        The validation outcome.
    """
    complete_object_ids = frozenset(
        int(object_id)
        for object_id in complete_dataframe[peri_scribe.models.OBJECT_ID_COLUMN_NAME]
    )
    complete_columns = attribute_columns_of(complete_dataframe)
    if (
        stored_dataframe is None
        or peri_scribe.models.OBJECT_ID_COLUMN_NAME not in stored_dataframe
    ):
        return FeedValidationResult(
            feed_name=feed.name,
            complete_feature_count=len(complete_dataframe),
            missing_object_ids=complete_object_ids,
            mismatched_object_ids=frozenset(),
            columns_missing_from_stored=complete_columns,
        )
    columns_missing_from_stored = complete_columns - attribute_columns_of(
        stored_dataframe,
    )
    columns = peri_scribe.changes.attribute_columns(
        complete_dataframe,
        stored_dataframe,
    )
    complete_contents = feature_contents(complete_dataframe, columns)
    stored_contents = feature_contents(stored_dataframe, columns)
    stored_object_ids = frozenset(stored_contents)
    mismatched_object_ids = frozenset(
        object_id
        for object_id in complete_object_ids & stored_object_ids
        if not feature_contents_equal(
            complete_contents[object_id],
            stored_contents[object_id],
        )
    )
    return FeedValidationResult(
        feed_name=feed.name,
        complete_feature_count=len(complete_dataframe),
        missing_object_ids=complete_object_ids - stored_object_ids,
        mismatched_object_ids=mismatched_object_ids,
        columns_missing_from_stored=frozenset(columns_missing_from_stored),
    )


def validate_complete_sources(
    year_directory: pathlib.Path,
    feeds: typing.Iterable[peri_scribe.feed_types.Feed],
) -> tuple[FeedValidationResult, ...]:
    """Validate each feed's stored snapshots against its complete snapshot.

    Each feed's complete snapshot is read from the sources-complete directory and
    compared against the latest stored feature per OBJECTID in the sources directory.

    Args:
        year_directory: The year directory holding both the sources and
            sources-complete directories.
        feeds: The feeds to validate.

    Returns:
        The validation outcome for each feed, in feed order.
    """
    results: list[FeedValidationResult] = []
    for feed in feeds:
        complete_path = peri_scribe.snapshots.sources_complete_geopackage_path(
            year_directory,
            feed.name,
        )
        complete_dataframe = peri_scribe.geo_package.read_layer_dataframe(
            complete_path,
            feed,
        )
        stored_dataframe = peri_scribe.changes.existing_features(
            peri_scribe.snapshots.sources_directory_path(year_directory) / feed.name,
            feed,
        )
        results.append(validate_feed(feed, complete_dataframe, stored_dataframe))
    return tuple(results)
