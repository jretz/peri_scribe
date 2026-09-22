"""Replace external sources dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import types
import typing

import arcgis_access.data
import peri_scribe.geo.data
import peri_scribe.sources.catalog
import peri_scribe.sources.external_sources
import tests.helpers.doubles.peri_scribe.sources.external_source


if typing.TYPE_CHECKING:
    import geopandas
    import pytest

YEAR_DIRECTORY = pathlib.Path("/data/2026")


WEB_MERCATOR_WKID = 3857


def install_arcgis_query_stubs(
    monkeypatch: pytest.MonkeyPatch,
    dataframe: geopandas.GeoDataFrame,
) -> None:
    """Point the ArcGIS query pipeline at a fake layer returning *dataframe*.

    Args:
        monkeypatch: The monkeypatch fixture.
        dataframe: The GeoDataFrame the fake pipeline returns.
    """
    monkeypatch.setattr(peri_scribe.sources.external_sources.arcgis.gis, "GIS", object)
    monkeypatch.setattr(
        peri_scribe.sources.external_sources.arcgis.features,
        "FeatureLayer",
        lambda _url, _gis: object(),
    )
    feature_set = types.SimpleNamespace(features=[object()], sdf=None)
    monkeypatch.setattr(
        peri_scribe.geo.data,
        "query_with_retry",
        lambda *_args, **_kwargs: feature_set,
    )
    monkeypatch.setattr(
        arcgis_access.data,
        "extract_geometries",
        lambda dataframe: (dataframe, [], None),
    )
    monkeypatch.setattr(
        arcgis_access.data,
        "geo_data_frame_from",
        lambda *_args, **_kwargs: dataframe,
    )


def make_named_query_recorder(
    *,
    queries: list[tuple[str, dict[str, object]]],
    feature_set: types.SimpleNamespace,
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Capture the feed name and query parameters used for a source snapshot.

    Args:
        queries: Shared list recording the intercepted query inputs.
        feature_set: Controlled query response returned without remote access.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def query(name: str, _layer: object, *, parameters: dict[str, object]) -> object:
        """Capture the feed name and query parameters used for a source snapshot.

        Args:
            name: Feed name recorded alongside the query parameters.
            _layer: ArcGIS layer accepted for query compatibility.
            parameters: Parameters supplied to the intercepted query or command.

        Returns:
            The configured source feature set.
        """
        queries.append((name, parameters))
        return feature_set

    return query


def make_query_filter_recorder(
    *,
    queries: list[dict[str, object]],
    feature_set: types.SimpleNamespace,
) -> typing.Callable[..., object]:
    """Create a callback with controlled dependencies.

    Capture the filter parameters passed to an external-source query.

    Args:
        queries: Shared list recording the intercepted query inputs.
        feature_set: Controlled query response returned without remote access.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def query(_name: str, _layer: object, *, parameters: dict[str, object]) -> object:
        """Capture the filter parameters passed to an external-source query.

        Args:
            _name: Feed name accepted for query compatibility.
            _layer: ArcGIS layer accepted for query compatibility.
            parameters: Parameters supplied to the intercepted query or command.

        Returns:
            The configured source feature set.
        """
        queries.append(parameters)
        return feature_set

    return query


def make_building_responder(
    *,
    urls: list[str],
    page: str,
    archive: bytes,
) -> typing.Callable[
    ...,
    tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse,
]:
    """Create a callback with controlled dependencies.

    Capture building download URLs and serve the configured content.

    Args:
        urls: Shared list recording requested download URLs.
        page: Buildings index HTML served before archive requests.
        archive: Archive contents served for a state download request.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def get(
        url: str,
        **kwargs: object,
    ) -> tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse:
        """Capture building download URLs and serve the configured content.

        Args:
            url: ArcGIS layer or download URL supplied by the caller.
            kwargs: HTTP request options accepted by the response substitute.

        Returns:
            The buildings index or archive selected by the URL.
        """
        urls.append(url)
        if url == peri_scribe.sources.catalog.BUILDINGS_SOURCE.url:
            return (
                tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                    page.encode("utf-8"),
                )
            )
        return tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
            archive,
        )

    return get
