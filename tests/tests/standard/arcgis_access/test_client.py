import arcgis.features
import arcgis.gis
import pytest

import arcgis_access.client


def test_client_exposes_the_initialized_sdk_modules() -> None:
    assert arcgis_access.client.features is arcgis.features
    assert arcgis_access.client.gis is arcgis.gis


def test_client_rejects_unknown_attributes() -> None:
    attribute = "unknown"
    with pytest.raises(AttributeError, match=attribute):
        getattr(arcgis_access.client, attribute)
