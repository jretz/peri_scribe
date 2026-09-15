"""Provide data builders and stand-ins for main run tests."""

from __future__ import annotations

import pathlib
import typing


def make_digest_recorder(
    *,
    digests: list[tuple[pathlib.Path, str]],
) -> typing.Callable[..., str | None]:
    """Create a callback with controlled dependencies.

    Capture which stored layer contributes the evacuation digest.

    Args:
        digests: Shared list recording GeoPackage paths and layers used for digests.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def stored_geopackage_digest(path: pathlib.Path, layer_name: str) -> str | None:
        """Capture which stored layer contributes the evacuation digest.

        Args:
            path: Path supplied to the intercepted file operation.
            layer_name: Name of the layer to select within the GeoPackage.

        Returns:
            A fixed digest representing the stored evacuation contents.
        """
        digests.append((path, layer_name))
        return "digest"

    return stored_geopackage_digest


def raise_malformed_state(_path: pathlib.Path) -> typing.Never:
    """Simulate a malformed full-fetch checkpoint.

    Args:
        _path: File path accepted for compatibility; the configured stub outcome is
            used.

    Raises:
        ValueError: Always, to exercise checkpoint validation failure.
    """
    message = "boom"
    raise ValueError(message)
