"""Configured source metadata is independent of its collectors."""

from __future__ import annotations

import pytest
import requests
import us

import peri_scribe.exceptions
import peri_scribe.sources.catalog
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.sources.external_source
import tests.helpers.factories.peri_scribe.sources.external_source


def test_buildings_source_covers_every_us_state() -> None:
    states = peri_scribe.sources.catalog.BUILDINGS_SOURCE.states
    assert len(states) == len(us.states.STATES) + 1
    assert "California" in states
    assert "District of Columbia" in states


def test_every_external_source_has_a_retrieval_url() -> None:
    for source in peri_scribe.sources.catalog.EXTERNAL_SOURCES:
        assert source.url
        if not source.compact_database:
            assert source.layer_name


def test_buildings_state_urls_reads_repo_page_every_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    links = {
        state: f"https://example.com/{state.replace(' ', '')}.geojson.zip"
        for state in peri_scribe.sources.catalog.BUILDINGS_STATES
    }
    urls: list[str] = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **_kwargs: (
            urls.append(url)
            or tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                tests.helpers.factories.peri_scribe.sources.external_source.buildings_page_html(
                    links,
                ).encode("utf-8"),
            )
        ),
    )

    result = peri_scribe.sources.catalog.buildings_state_urls()
    assert urls == ["https://github.com/microsoft/USBuildingFootprints"]
    assert result == links
    assert result["New Hampshire"] == ("https://example.com/NewHampshire.geojson.zip")


def test_buildings_state_urls_raises_when_page_has_nodownload_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                b"<html><body><p>hi</p></body></html>",
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download links found",
    ):
        peri_scribe.sources.catalog.buildings_state_urls()


def test_buildings_state_urls_raises_when_a_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = (
        tests.helpers.factories.peri_scribe.sources.external_source
    ).buildings_page_html({
        "California": "https://example.com/California.geojson.zip",
    })
    monkeypatch.setattr(
        requests,
        "get",
        lambda _url, **_kwargs: (
            tests.helpers.doubles.peri_scribe.sources.external_source.FakeResponse(
                page.encode("utf-8"),
            )
        ),
    )
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match="No download link for Alabama",
    ):
        peri_scribe.sources.catalog.buildings_state_urls()


def test_buildings_state_urls_raises_when_page_cannot_be_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail = tests.helpers.doubles.errors.raising_stub(
        requests.exceptions.RequestException("boom"),
    )

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(
        peri_scribe.exceptions.ExternalDataError,
        match=(
            r"Failed to download https://github\.com/microsoft/USBuildingFootprints: "
            r"boom"
        ),
    ):
        peri_scribe.sources.catalog.buildings_state_urls()
