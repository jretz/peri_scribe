"""Replace arcgis dependencies with controlled test doubles."""

from __future__ import annotations

import arcgis.features

import tests.helpers.factories.geography


class LayerStub(arcgis.features.FeatureLayer):
    """Minimal stand-in for an ArcGIS FeatureLayer exposing properties."""

    def __init__(self, properties: dict[str, object]) -> None:
        """Initialize a layer with controlled ArcGIS metadata.

        Args:
            properties: ArcGIS metadata exposed by the layer's properties accessor.
        """
        self.layer_properties = properties

    @property
    def properties(self) -> dict[str, object]:
        """The ArcGIS metadata supplied to this layer stub.

        Returns:
            The configured layer properties.
        """
        return self.layer_properties


class FeatureSetStub(arcgis.features.FeatureSet):
    """Minimal stand-in for an ArcGIS FeatureSet exposing spatial_reference."""

    def __init__(self, spatial_reference: object) -> None:
        """Initialize a feature set with a controlled spatial reference.

        Args:
            spatial_reference: Spatial-reference value exposed by the feature-set stub.
        """
        self.stored_spatial_reference = spatial_reference

    @property
    def spatial_reference(self) -> object:
        """The spatial reference supplied to this feature-set stub.

        Returns:
            The configured spatial-reference value.
        """
        return self.stored_spatial_reference


class FeatureLayerStubBase:
    """Base stand-in for an ArcGIS FeatureLayer exposing WGS84 properties."""

    def __init__(self, url: str, gis: object) -> None:
        """Initialize a layer stub with WGS84 metadata and its connection inputs.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
        """
        self.url = url
        self.gis = gis
        self.layer_properties: dict[str, object] = {
            "spatialReference": {"wkid": tests.helpers.factories.geography.WGS84_WKID},
        }

    @property
    def properties(self) -> dict[str, object]:
        """The layer metadata exposed to spatial-reference selection.

        Returns:
            The configured properties, including the WGS84 reference.
        """
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
        """Initialize a layer with a fixed query result or failure.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            gis: GIS connection object supplied to the layer constructor.
            feature_set: Feature set returned by the controlled query.
            query_error: Exception to raise during queries, or None for a successful
                response.
        """
        super().__init__(url, gis)
        self.feature_set = feature_set
        self.query_error = query_error

    def query(self, **kwargs: object) -> arcgis.features.FeatureSet | dict[str, object]:
        """Serve the configured query result for isolated ArcGIS tests.

        Args:
            kwargs: Parameters supplied to the intercepted query or command.

        Returns:
            The fixed object identifiers for ID-only queries, otherwise the feature set.

        Raises:
            The configured query error, when one was supplied to the constructor.
        """
        if self.query_error is not None:
            raise self.query_error
        if kwargs.get("return_ids_only"):
            return {"objectIdFieldName": "OBJECTID", "objectIds": [1, 2]}
        return self.feature_set
