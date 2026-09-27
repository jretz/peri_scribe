"""Inject interruption after a cache staging write has produced readable data."""

from __future__ import annotations

import pathlib
import typing

import spatial_data.layers


if typing.TYPE_CHECKING:
    import pytest


def fail_after_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve the real serializer while failing before publication can complete.

    Args:
        monkeypatch: Isolated dependency replacement scope.
    """
    original = spatial_data.layers.write_geopackage

    def write(path: pathlib.Path, layers: list[spatial_data.layers.LayerData]) -> None:
        """Expose the completed write boundary to a simulated interruption.

        Args:
            path: Destination selected by production cache persistence.
            layers: Cache rows selected by production reconciliation.

        Raises:
            RuntimeError: After the serializer has written the cache.
        """
        original(
            path,
            [
                spatial_data.layers.LayerData(
                    name=layer.name,
                    dataframe=layer.dataframe.iloc[:1],
                )
                for layer in layers
            ],
        )
        message = "interrupted cache write"
        raise RuntimeError(message)

    monkeypatch.setattr(spatial_data.layers, "write_geopackage", write)
