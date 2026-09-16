"""Replace sources dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.exceptions
import peri_scribe.models


class StubFireReader(typing.Protocol):
    """A function that installs in-memory fire and membership stand-ins."""

    def __call__(
        self,
        records_by_path: dict[pathlib.Path, list[peri_scribe.models.FireRecord]],
        memberships_by_path: dict[
            pathlib.Path,
            list[peri_scribe.models.ComplexMembership],
        ]
        | None = None,
    ) -> None:
        """Install the observations and memberships a reader test requires.

        Args:
            records_by_path: Fire observations to serve for each GeoPackage path.
            memberships_by_path: Complex memberships to serve per path, or None for no
                memberships.
        """
        ...


def raise_unknown_layer(_path: pathlib.Path) -> typing.Never:
    """Simulate a snapshot containing an unconfigured layer.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        peri_scribe.exceptions.UnknownLayerError: Always, for the synthetic unknown
            layer.
    """
    layer_name = "Mystery_Layer_0"
    raise peri_scribe.exceptions.UnknownLayerError(
        layer_name,
        pathlib.Path("fires.gpkg"),
    )


def raise_missing_snapshot(_path: pathlib.Path) -> typing.Never:
    """Simulate a snapshot disappearing before it can be read.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        FileNotFoundError: Always, to exercise unreadable-source handling.
    """
    message = "no such file"
    raise FileNotFoundError(message)
