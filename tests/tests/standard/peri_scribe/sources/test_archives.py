"""Tests for peri_scribe.sources.archives."""

from __future__ import annotations

import peri_scribe.sources.archives
import tests.helpers.factories.peri_scribe.sources.external_source


def test_download_links_stops_at_an_unwrapped_heading() -> None:
    page = (
        "<h1>Download links</h1><h1>Contributing</h1>"
        '<a href="https://example.test/after.zip">Outside</a>'
    )
    assert peri_scribe.sources.archives.download_links(page) == {}


def test_download_links_parses_github_page_table() -> None:
    links = {
        "California": (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            "usbuildings-v2/California.geojson.zip"
        ),
        "New Hampshire": (
            "https://minedbuildings.z5.web.core.windows.net/legacy/"
            "usbuildings-v2/NewHampshire.geojson.zip"
        ),
    }
    page = (
        tests.helpers.factories.peri_scribe.sources.external_source.buildings_page_html(
            links,
        )
    )
    assert peri_scribe.sources.archives.download_links(page) == links


def test_download_links_matches_downloads_links_heading() -> None:
    page = (
        (tests.helpers.factories.peri_scribe.sources.external_source)
        .buildings_page_html({
            "California": "https://example.com/California.geojson.zip",
        })
        .replace("Download links", "Downloads links")
    )
    assert peri_scribe.sources.archives.download_links(page) == {
        "California": "https://example.com/California.geojson.zip",
    }
