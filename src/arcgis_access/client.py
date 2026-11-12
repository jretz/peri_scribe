"""Load the ArcGIS SDK when an operation needs its client or feature types."""

import importlib
import types
import typing


if typing.TYPE_CHECKING:
    from arcgis import features, gis


__all__ = ("features", "gis")


def __getattr__(name: str) -> types.ModuleType:
    """Resolve the real SDK modules for operations that contact ArcGIS.

    Args:
        name: The SDK submodule requested by the caller.

    Returns:
        The registered SDK module with its normal initialization complete.

    Raises:
        AttributeError: The adapter does not expose the requested attribute.
    """
    if name not in {"features", "gis"}:
        raise AttributeError(name)
    return importlib.import_module(f"arcgis.{name}")
