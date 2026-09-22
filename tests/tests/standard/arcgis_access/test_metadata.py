"""Tests for ArcGIS metadata transport options."""

from __future__ import annotations

import typing
import unittest.mock

import arcgis_access.metadata


if typing.TYPE_CHECKING:
    import requests_mock


def test_fetch_layer_metadata_uses_caller_transport_options() -> None:
    timeout_seconds = 17
    response = unittest.mock.Mock()
    response.json.return_value = {"editingInfo": {"lastEditDate": 123}}
    with unittest.mock.patch("requests.get", return_value=response) as request:
        result = arcgis_access.metadata.fetch_layer_metadata(
            "https://example.com/FeatureServer/0",
            user_agent="layer-client/2",
            timeout_seconds=timeout_seconds,
        )
    assert result == {"editingInfo": {"lastEditDate": 123}}
    assert request.call_args.kwargs["headers"] == {"User-Agent": "layer-client/2"}
    assert request.call_args.kwargs["timeout"] == timeout_seconds
    assert request.call_args.kwargs["params"]["f"] == "json"
    assert isinstance(request.call_args.kwargs["params"]["_cb"], int)
    response.raise_for_status.assert_called_once_with()


def test_observe_layer_last_edit_timestamp_reads_a_generic_layer(
    requests_mock: requests_mock.Mocker,
) -> None:
    url = "https://example.com/FeatureServer/2"
    last_edit_timestamp = 456
    requests_mock.get(
        url,
        json={"editingInfo": {"lastEditDate": str(last_edit_timestamp)}},
    )
    assert (
        arcgis_access.metadata.observe_layer_last_edit_timestamp(
            url,
            "Stations",
            user_agent="layer-client/2",
            timeout_seconds=17,
        )
        == last_edit_timestamp
    )
