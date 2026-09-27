"""Bind the cache model's exact data values to production merge and freshness logic."""

from __future__ import annotations

import dataclasses
import pathlib
import re
import typing

import peri_scribe.geo.reading
import peri_scribe.sources.feed_state
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import spatial_data.layers
import tests.helpers.factories.peri_scribe.sources.feed_state
import tests.helpers.factories.peri_scribe.sources.feed_types


if typing.TYPE_CHECKING:
    import geopandas
    import pytest


def values(text: str) -> list[int]:
    """Decode TLC's finite object vector without reimplementing its merge policy.

    Args:
        text: A TLC sequence containing nonnegative integer values.

    Returns:
        Values in object identity order.
    """
    return [int(value) for value in re.findall(r"\d+", text)]


def frame(pairs: list[tuple[int, int]]) -> geopandas.GeoDataFrame:
    """Retain only the model's present objects in a real geometry dataframe.

    Args:
        pairs: Object identities and positive values.

    Returns:
        The production-shaped feature frame.
    """
    return tests.helpers.factories.peri_scribe.sources.feed_state.feature_frames(
        [[(identifier, str(value)) for identifier, value in pairs if value]],
    )[0]


@dataclasses.dataclass(kw_only=True)
class Files:
    """Replace only GeoPackage serialization while preserving actual cache decisions."""

    frames: dict[pathlib.Path, geopandas.GeoDataFrame]
    unreadable: pathlib.Path | None
    written: geopandas.GeoDataFrame | None = None

    def read(
        self,
        path: pathlib.Path,
        _feed: peri_scribe.sources.feed_types.Feed,
    ) -> geopandas.GeoDataFrame:
        """Deliver the model's source bytes or its explicit unreadable-cache fault.

        Args:
            path: Path chosen by production source selection.
            _feed: Layer selector supplied by the production function.

        Returns:
            The corresponding feature frame.

        Raises:
            OSError: When the checked model marks the cache unreadable.
        """
        if path == self.unreadable:
            message = "modeled unreadable cache"
            raise OSError(message)
        return self.frames[path]

    def write(
        self,
        path: pathlib.Path,
        layers: list[spatial_data.layers.LayerData],
    ) -> None:
        """Keep production atomic rename active while observing serialized values.

        Args:
            path: Staging path chosen by production persistence.
            layers: Complete output selected by the production merge.
        """
        assert len(layers) == 1
        self.written = layers[0].dataframe
        path.touch()


def replay(
    state: dict[str, str],
    directory: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise every checked cache input against the TLC candidate, including gaps.

    Args:
        state: A state immediately before its checked atomic cache publication.
        directory: Isolated location for real staging and rename operations.
        monkeypatch: Per-test replacement scope for serialization boundaries.
    """
    updates = [
        (int(identifier), int(value))
        for identifier, value in re.findall(
            r"object \|-> (\d+), value \|-> (\d+)",
            state["updates"],
        )
    ]
    count, tag = int(state["count"]), int(state["tag"])
    sources = [
        peri_scribe.sources.snapshots.SourceFile(
            serial_number=index,
            last_edit_timestamp=0,
        )
        for index in range(1, count + 1)
    ]
    state_path = peri_scribe.sources.snapshots.current_state_path(directory, tag)
    files = Files(
        frames={
            directory / source.relative_path: frame([updates[index]])
            for index, source in enumerate(sources)
        },
        unreadable=state_path if state["readable"] == "FALSE" else None,
    )
    files.frames[state_path] = frame(list(enumerate(values(state["cache"]), 1)))
    monkeypatch.setattr(peri_scribe.geo.reading, "read_layer_dataframe", files.read)
    monkeypatch.setattr(spatial_data.layers, "write_geopackage", files.write)
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "existing_source_files",
        lambda _directory: sources,
    )
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "current_state_file_paths",
        lambda _directory: [] if tag == 0 else [(tag, state_path)],
    )
    peri_scribe.sources.feed_state.write_current_state(
        directory,
        tests.helpers.factories.peri_scribe.sources.feed_types.change_feed(),
        frame([updates[count - 1]]),
    )
    assert files.written is not None
    actual = dict(zip(files.written["OBJECTID"], files.written["value"], strict=True))
    expected = {
        identifier: str(value)
        for identifier, value in enumerate(values(state["candidate"]), 1)
        if value
    }
    assert actual == expected, state
