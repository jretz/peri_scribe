"""Keep snapshot interruption tests on real isolated filesystem boundaries."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.sources.feed_state
import peri_scribe.sources.fetching
import tests.helpers.factories.peri_scribe.sources.fetching


if typing.TYPE_CHECKING:
    import geopandas
    import pytest

    import spatial_data.layers


class Interrupted(BaseException):
    """Represent termination while a file contains an incomplete GeoPackage."""


def configure_fetch(monkeypatch: pytest.MonkeyPatch) -> geopandas.GeoDataFrame:
    """Supply one new observation without replacing snapshot discovery or file writes.

    Args:
        monkeypatch: Restore replaced service and derived-cache boundaries afterward.

    Returns:
        The new observation the service supplies.
    """
    dataframe = tests.helpers.factories.peri_scribe.sources.fetching.fetch_frame({
        1: tests.helpers.factories.peri_scribe.sources.fetching.FetchFeature(
            name="New observation",
            active=True,
            modified_minute=1,
            longitude=-120,
        ),
    })
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "open_feed_connection",
        lambda _feed: object(),
    )
    monkeypatch.setattr(
        peri_scribe.sources.fetching,
        "fetch_feed",
        lambda *_args, **_kwargs: dataframe,
    )
    monkeypatch.setattr(
        peri_scribe.sources.feed_state,
        "write_current_state",
        lambda *_args: None,
    )
    return dataframe


def interrupt_write(
    path: pathlib.Path,
    layers: list[spatial_data.layers.LayerData],
) -> None:
    """Leave partial bytes so filename-based recovery must reject them.

    Args:
        path: Destination selected by production snapshot publication.
        layers: The complete observations awaiting serialization.

    Raises:
        Interrupted: After a prefix of the output becomes visible on disk.
    """
    assert layers
    path.write_bytes(b"incomplete GeoPackage")
    raise Interrupted
