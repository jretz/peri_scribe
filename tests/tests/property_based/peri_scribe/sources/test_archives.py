"""Tests for peri_scribe.sources.archives."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import peri_scribe.sources.archives
import tests.helpers.strategies.peri_scribe.sources.archives


@hypothesis.given(
    page=tests.helpers.strategies.peri_scribe.sources.archives.download_pages(),
)
def test_download_links_preserves_only_the_download_section(
    page: tests.helpers.strategies.peri_scribe.sources.archives.DownloadPage,
) -> None:
    assert peri_scribe.sources.archives.download_links(page.html_text) == page.links


@hypothesis.given(
    page=tests.helpers.strategies.peri_scribe.sources.archives.download_pages(),
    chunk_size=hypothesis.strategies.integers(1, 100),
)
def test_download_links_parser_feed_is_independent_of_chunk_boundaries(
    page: tests.helpers.strategies.peri_scribe.sources.archives.DownloadPage,
    chunk_size: int,
) -> None:
    parser = peri_scribe.sources.archives.DownloadLinksParser()
    for offset in range(0, len(page.html_text), chunk_size):
        parser.feed(page.html_text[offset : offset + chunk_size])
    parser.close()
    assert parser.links == peri_scribe.sources.archives.download_links(page.html_text)
