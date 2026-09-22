"""Exercise reusable spatial layer operations."""

from __future__ import annotations

import pathlib
import typing

import geopandas


if typing.TYPE_CHECKING:
    import pytest


def make_recording_layer_reader(
    *,
    calls: list[tuple[pathlib.Path, str]],
    frame: geopandas.GeoDataFrame,
) -> typing.Callable[..., geopandas.GeoDataFrame]:
    """Create a callback to capture the selected GeoPackage path and layer.

    Args:
        calls: Shared list recording dependency calls for assertions.
        frame: Dataframe returned by the layer reader.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def read_file(read_path: pathlib.Path, *, layer: str) -> geopandas.GeoDataFrame:
        """Capture the selected GeoPackage path and layer.

        Args:
            read_path: GeoPackage path requested by the layer reader.
            layer: Layer name requested within the GeoPackage.

        Returns:
            The dataframe configured for this reader test.
        """
        calls.append((read_path, layer))
        return frame

    return read_file


def stub_to_file(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[pathlib.Path, str, str, str]]:
    """Record GeoDataFrame.to_file calls.

    Args:
        monkeypatch: The monkeypatch fixture.

    Returns:
        The recorded (path, driver, layer, mode) calls.
    """
    calls: list[tuple[pathlib.Path, str, str, str]] = []
    monkeypatch.setattr(
        geopandas.GeoDataFrame,
        "to_file",
        lambda _self, path, driver, layer, mode: calls.append((
            path,
            driver,
            layer,
            mode,
        )),
    )
    return calls


def make_unlink_recorder(*, unlinked: list[pathlib.Path]) -> typing.Callable[..., None]:
    """Create a callback to capture which existing output file is removed.

    Args:
        unlinked: Shared list recording paths selected for removal.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def fake_unlink(_self: pathlib.Path) -> None:
        """Capture which existing output file is removed.

        Args:
            _self: Path receiving the intercepted filesystem operation.
        """
        unlinked.append(_self)

    return fake_unlink
