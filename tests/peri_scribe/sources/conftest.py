"""Provide isolated fixtures for this test package."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.fires.index
import peri_scribe.sources.feeds
import peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import tests.peri_scribe.sources.fetching_helpers


@pytest.fixture
def fetch_all_feeds_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Callable[
    [
        list[tests.peri_scribe.sources.fetching_helpers.FeedStub],
        typing.Callable[[str, object], object],
    ],
    None,
]:
    """Install feed, GIS, and FeatureLayer stubs for fetch-all-feeds tests.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.

    Returns:
        A callable that installs the stubs for one test.
    """

    def install(
        feeds: list[tests.peri_scribe.sources.fetching_helpers.FeedStub],
        layer_factory: typing.Callable[[str, object], object],
    ) -> None:
        """Install feed and layer substitutes for an isolated collection run.

        Args:
            feeds: Feed configurations to include in the collection or validation.
            layer_factory: Construct a controlled layer for each feed URL and GIS
                connection.
        """
        monkeypatch.setattr(peri_scribe.sources.feeds, "FEEDS", feeds)
        monkeypatch.setattr(peri_scribe.sources.fetching.arcgis.gis, "GIS", object)
        monkeypatch.setattr(
            peri_scribe.sources.fetching.arcgis.features,
            "FeatureLayer",
            layer_factory,
        )
        monkeypatch.setattr(
            peri_scribe.fires.index,
            "index_fire_sources",
            lambda _year_directory: None,
        )

    return install
