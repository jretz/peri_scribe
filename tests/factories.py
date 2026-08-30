"""Factories for building fire records and feeds in tests."""

from __future__ import annotations

import datetime
import pathlib
import typing

import arcgis.features
import geopandas
import pyproj
import pyproj.exceptions
import shapely
import shapely.geometry

import peri_scribe.california_border_classification
import peri_scribe.feed_types
import peri_scribe.models
import peri_scribe.perimeter_versions
import peri_scribe.snapshots


ACTIVE = peri_scribe.models.FireStatus.ACTIVE


INACTIVE = peri_scribe.models.FireStatus.INACTIVE


FIRIS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.FIRIS_PERIMETER
)
WFIGS_PERIMETER = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_PERIMETER
)
WFIGS_LOCATION = (
    peri_scribe.california_border_classification.FireSourceKind.WFIGS_LOCATION
)


WGS84_WKID = 4326


class StubFireReader(typing.Protocol):
    """A function that installs in-memory fire and membership stand-ins."""

    def __call__(
        self,
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None: ...


def fire_record(
    name: str,
    status: peri_scribe.models.FireStatus,
    identifiers: typing.Iterable[str] = (),
    *,
    names: typing.Iterable[str] | None = None,
    geometry: shapely.Geometry | None = None,
    observed_at: datetime.datetime | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for a test.

    Args:
        name: The record's display name.
        status: The record's status.
        identifiers: The record's normalized identifiers.
        names: The record's normalized name keys; defaults to the display name's
            normalization.
        geometry: The record's geometry.
        observed_at: The record's observation time.

    Returns:
        The record.
    """
    name_keys = (
        frozenset(names)
        if names is not None
        else frozenset({peri_scribe.models.normalize_fire_name(name)})
    )
    return peri_scribe.models.FireRecord(
        name=name,
        status=status,
        identifiers=frozenset(identifiers),
        names=name_keys,
        geometry=geometry,
        observed_at=observed_at,
    )


def change_feed(
    change_columns: tuple[str, ...] = ("ModifiedOnDateTime_dt",),
) -> peri_scribe.feed_types.Feed:
    """Return a feed with known change columns.

    Args:
        change_columns: The timestamp columns that change when a feature is edited.

    Returns:
        The feed.
    """
    return peri_scribe.feed_types.ArcGISFeed(
        url="https://example.test/ArcGIS/rest/services/Fires/FeatureServer/0",
        fire_name_column="name",
        status_column="status",
        change_columns=change_columns,
    )


def change_dataframe(
    rows: list[tuple[int, str, tuple[float, float]]],
) -> geopandas.GeoDataFrame:
    """Return a GeoDataFrame of point features for the given rows.

    Args:
        rows: The OBJECTID, name, and coordinates of each feature.

    Returns:
        The GeoDataFrame.
    """
    return geopandas.GeoDataFrame(
        {
            "OBJECTID": [row[0] for row in rows],
            "name": [row[1] for row in rows],
        },
        geometry=[shapely.geometry.Point(row[2]) for row in rows],
        crs=pyproj.CRS.from_epsg(4326),
    )


def polygon(*points: tuple[float, float]) -> shapely.geometry.Polygon:
    """Return a polygon from *points*.

    Args:
        points: The polygon's exterior points.

    Returns:
        The polygon.
    """
    return shapely.geometry.Polygon(points)


def point(x: float, y: float) -> shapely.geometry.Point:
    """Return a point at *x*, *y*.

    Args:
        x: The longitude.
        y: The latitude.

    Returns:
        The point.
    """
    return shapely.geometry.Point(x, y)


def observation(
    *,
    source_kind: peri_scribe.california_border_classification.FireSourceKind = (
        FIRIS_PERIMETER
    ),
    geometry: shapely.geometry.base.BaseGeometry | None = None,
    observation_time: datetime.datetime | None = None,
    snapshot_time: datetime.datetime | None = None,
    serial_number: int = 0,
    object_id: int | None = 1,
    source_file: str = "source.gpkg",
    attributes: dict[str, object] | None = None,
) -> peri_scribe.perimeter_versions.SourceObservation:
    """Build a source observation for a test.

    Args:
        source_kind: The observation's source kind.
        geometry: The observation's geometry.
        observation_time: The mapping time.
        snapshot_time: The snapshot's last-edit time.
        serial_number: The snapshot serial number.
        object_id: The source row's OBJECTID.
        source_file: The source file path.
        attributes: The row's attributes.

    Returns:
        The observation.
    """
    return peri_scribe.perimeter_versions.SourceObservation(
        source_kind=source_kind,
        geometry=geometry,
        observation_time=observation_time,
        snapshot_time=snapshot_time,
        serial_number=serial_number,
        object_id=object_id,
        source_file=source_file,
        attributes={} if attributes is None else attributes,
    )


def fire(
    name: str = "Bug",
    identifier: str | None = "2026-nvccd-030683",
) -> peri_scribe.models.Fire:
    """Build a fire for a test.

    Args:
        name: The fire's name.
        identifier: The fire's canonical identifier.

    Returns:
        The fire.
    """
    return peri_scribe.models.Fire(
        name=name,
        status=ACTIVE,
        identifier=identifier,
        aliases=frozenset({identifier}) if identifier is not None else frozenset(),
    )


def classification(
    kind: peri_scribe.models.BorderClassification,
) -> peri_scribe.models.FireClassification:
    """Build a border classification for a test.

    Args:
        kind: The classification kind.

    Returns:
        The classification.
    """
    return peri_scribe.models.FireClassification(
        classification=kind,
        distance_to_boundary_in_meters=0.0,
        outside_area_fraction=0.0,
        inside_area_fraction=0.0,
    )


def utc(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    *,
    second: int = 0,
) -> datetime.datetime:
    """Return an aware UTC datetime.

    Args:
        year: The year.
        month: The month.
        day: The day.
        hour: The hour.
        minute: The minute.
        second: The second.

    Returns:
        The datetime.
    """
    return datetime.datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=datetime.UTC,
    )


class LayerStub(arcgis.features.FeatureLayer):
    """Minimal stand-in for an ArcGIS FeatureLayer exposing properties."""

    def __init__(self, properties: dict[str, object]) -> None:
        self.layer_properties = properties

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties


class FeatureSetStub(arcgis.features.FeatureSet):
    """Minimal stand-in for an ArcGIS FeatureSet exposing spatial_reference."""

    def __init__(self, spatial_reference: object) -> None:
        self.stored_spatial_reference = spatial_reference

    @property
    def spatial_reference(self) -> object:
        return self.stored_spatial_reference


class FeatureLayerStubBase:
    """Base stand-in for an ArcGIS FeatureLayer exposing WGS84 properties."""

    def __init__(self, url: str, gis: object) -> None:
        self.url = url
        self.gis = gis
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        return self.layer_properties


class FeatureLayerStub(FeatureLayerStubBase):
    """Minimal stand-in for an ArcGIS FeatureLayer with a fixed query result."""

    def __init__(
        self,
        url: str,
        gis: object,
        feature_set: arcgis.features.FeatureSet,
        query_error: Exception | None = None,
    ) -> None:
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.query_error = query_error

    def query(
        self,
        **parameters: object,
    ) -> arcgis.features.FeatureSet | dict[str, object]:
        if self.query_error is not None:
            raise self.query_error
        if parameters.get("return_ids_only"):
            return {"objectIdFieldName": "OBJECTID", "objectIds": [1, 2]}
        return self.feature_set


class FailingTransformer:
    """Transformer stand-in whose corner transforms always fail."""

    def transform(  # ruff: ignore[no-self-use]
        self,
        longitude: float,
        latitude: float,
    ) -> tuple[float, float]:
        message = f"transform failed at ({longitude}, {latitude})"
        raise pyproj.exceptions.ProjError(message)


def failing_from_crs(
    crs_from: str,
    crs_to: pyproj.CRS,
    *,
    always_xy: bool = True,
) -> FailingTransformer:
    return FailingTransformer()


def wgs84_feature_set(
    points: list[tuple[int | None, str, float, float]],
) -> arcgis.features.FeatureSet:
    """Build a WGS84 FeatureSet from (OBJECTID, name, x, y) point rows.

    Args:
        points: The OBJECTID (None to omit it), name, longitude, and latitude of
            each feature.

    Returns:
        The FeatureSet.
    """
    features = []
    for object_id, name, x, y in points:
        attributes: dict[str, object] = {"name": name}
        if object_id is not None:
            attributes["OBJECTID"] = object_id
        features.append(
            arcgis.features.Feature(
                geometry={
                    "x": x,
                    "y": y,
                    "spatialReference": {"wkid": WGS84_WKID},
                },
                attributes=attributes,
            ),
        )
    return arcgis.features.FeatureSet(features)


class GeoPackageStore:
    """In-memory stand-in for the GeoPackage files the fetch command writes.

    Written layers are keyed by (path, layer name) so tests can assert what was written
    and serve it back to incremental fetches without touching the filesystem.
    """

    def __init__(self) -> None:
        self.layers: dict[
            tuple[pathlib.Path, str],
            geopandas.GeoDataFrame,
        ] = {}

    def write(
        self,
        path: pathlib.Path,
        layers: list[peri_scribe.models.LayerData],
    ) -> None:
        """Record *layers* as the contents of the GeoPackage at *path*."""
        for layer_data in layers:
            self.layers[path, layer_data.name] = layer_data.dataframe

    def source_files(
        self,
        directory: pathlib.Path,
    ) -> list[peri_scribe.snapshots.SourceFile]:
        """Return the source files stored under *directory*, in serial order.

        Files that do not encode a snapshot serial number and timestamp (the
        current-state files) are skipped, mirroring ``existing_source_files``.

        Returns:
            The stored source files, sorted by serial number.
        """
        source_files: list[peri_scribe.snapshots.SourceFile] = []
        for path, _layer_name in self.layers:
            if path.suffix != ".gpkg" or not path.is_relative_to(directory):
                continue
            try:
                source_files.append(
                    peri_scribe.snapshots.SourceFile.from_path(path),
                )
            except ValueError:
                continue
        return sorted(source_files, key=lambda source_file: source_file.serial_number)

    def read_layer(
        self,
        path: pathlib.Path,
        feed: peri_scribe.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Return the layer for *feed* stored in the GeoPackage at *path*.

        Returns:
            The feed's layer dataframe.
        """
        return self.layers[path, feed.name]

    def layer(
        self,
        path: pathlib.Path,
        layer_name: str,
    ) -> geopandas.GeoDataFrame:
        """Return the layer named *layer_name* stored at *path*.

        Returns:
            The layer dataframe.
        """
        return self.layers[path, layer_name]

    def has(self, path: pathlib.Path) -> bool:
        """Return whether any layer has been stored at *path*.

        Returns:
            True when a layer has been stored at *path*.
        """
        return any(stored_path == path for stored_path, _layer_name in self.layers)
