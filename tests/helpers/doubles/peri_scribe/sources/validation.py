"""Replace validation dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


if typing.TYPE_CHECKING:
    import geopandas

    import peri_scribe.sources.feed_types


def make_complete_snapshot_reader(
    *,
    read_calls: list[tuple[pathlib.Path, peri_scribe.sources.feed_types.Feed]],
    complete_frames: dict[str, geopandas.GeoDataFrame],
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback with controlled dependencies.

    Capture complete-snapshot reads and serve the matching feed dataframe.

    Args:
        read_calls: Shared list recording complete-snapshot paths and feed
            configurations.
        complete_frames: Complete snapshot dataframes keyed by feed name.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_layer_dataframe(
        path: pathlib.Path,
        feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Capture complete-snapshot reads and serve the matching feed dataframe.

        Args:
            path: Path supplied to the intercepted file operation.
            feed: Feed configuration used to interpret the source observations.

        Returns:
            The configured complete snapshot for the requested feed.
        """
        read_calls.append((path, feed))
        return complete_frames[feed.name]

    return read_layer_dataframe


def make_stored_features_reader(
    *,
    year_directory: pathlib.Path,
    stored_frames: dict[str, geopandas.GeoDataFrame],
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback with controlled dependencies.

    Validate the source directory and serve the stored feed dataframe.

    Args:
        year_directory: Year directory against which source paths are checked.
        stored_frames: Stored observation dataframes keyed by feed name.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def existing_features(
        directory: pathlib.Path,
        feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Validate the source directory and serve the stored feed dataframe.

        Args:
            directory: Directory supplied to the intercepted storage operation.
            feed: Feed configuration used to interpret the source observations.

        Returns:
            The configured stored observations for the requested feed.
        """
        assert directory == year_directory / "sources" / feed.name
        return stored_frames[feed.name]

    return existing_features
