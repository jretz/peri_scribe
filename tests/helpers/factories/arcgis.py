"""Build inputs for arcgis tests."""

from __future__ import annotations

import arcgis.features

import tests.helpers.factories.geography


def wgs84_feature_set(
    points: list[tuple[int | None, str, float, float]],
) -> arcgis.features.FeatureSet:
    """Build a WGS84 FeatureSet from (OBJECTID, name, x, y) point rows.

    Args:
        points: The OBJECTID (None to omit it), name, longitude, and latitude of each
            feature.

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
                    "spatialReference": {
                        "wkid": tests.helpers.factories.geography.WGS84_WKID,
                    },
                },
                attributes=attributes,
            ),
        )
    return arcgis.features.FeatureSet(features)
