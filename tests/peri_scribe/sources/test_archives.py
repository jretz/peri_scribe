"""Tests for peri_scribe.sources.archives."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import peri_scribe.sources.archives
import tests.peri_scribe.sources.archives_helpers
import tests.peri_scribe.sources.external_source_helpers


@hypothesis.given(page=tests.peri_scribe.sources.archives_helpers.download_pages())
def test_download_links_preserves_only_the_download_section(
    page: tests.peri_scribe.sources.archives_helpers.DownloadPage,
) -> None:
    assert peri_scribe.sources.archives.download_links(page.html_text) == page.links


def test_download_links_stops_at_an_unwrapped_heading() -> None:
    page = (
        "<h1>Download links</h1><h1>Contributing</h1>"
        '<a href="https://example.test/after.zip">Outside</a>'
    )
    assert peri_scribe.sources.archives.download_links(page) == {}


@hypothesis.given(
    page=tests.peri_scribe.sources.archives_helpers.download_pages(),
    chunk_size=hypothesis.strategies.integers(1, 100),
)
def test_download_links_parser_feed_is_independent_of_chunk_boundaries(
    page: tests.peri_scribe.sources.archives_helpers.DownloadPage,
    chunk_size: int,
) -> None:
    parser = peri_scribe.sources.archives.DownloadLinksParser()
    for offset in range(0, len(page.html_text), chunk_size):
        parser.feed(page.html_text[offset : offset + chunk_size])
    parser.close()
    assert parser.links == peri_scribe.sources.archives.download_links(page.html_text)


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
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html(links)
    assert peri_scribe.sources.archives.download_links(page) == links


def test_download_links_matches_downloads_links_heading() -> None:
    page = tests.peri_scribe.sources.external_source_helpers.buildings_page_html({
        "California": "https://example.com/California.geojson.zip",
    }).replace("Download links", "Downloads links")
    assert peri_scribe.sources.archives.download_links(page) == {
        "California": "https://example.com/California.geojson.zip",
    }
