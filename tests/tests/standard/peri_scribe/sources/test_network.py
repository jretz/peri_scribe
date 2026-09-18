"""Streaming responses must close even when conversion stops early."""

import pytest
import requests

import peri_scribe.sources.network
import tests.helpers.doubles.peri_scribe.sources.external_source


def test_downloaded_response_closes_after_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
        b"payload",
    )
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response)
    with peri_scribe.sources.network.downloaded_response(
        "https://example.test",
        stream=True,
    ) as opened:
        assert next(opened.iter_content(chunk_size=1)) == b"p"
    assert response.closed


def test_downloaded_response_closes_after_conversion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
        b"payload",
    )
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response)
    message = "conversion failed"
    with (
        pytest.raises(ValueError, match="conversion failed"),
        peri_scribe.sources.network.downloaded_response(
            "https://example.test",
            stream=True,
        ),
    ):
        raise ValueError(message)
    assert response.closed
