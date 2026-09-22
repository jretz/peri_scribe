"""Exception classes for peri_scribe."""

import pathlib


class FeedFetchError(ValueError):
    """Raised when a configured feed cannot be fetched."""


class AdministrativeBoundariesError(ValueError):
    """Raised when administrative boundary data cannot be produced."""


class ExternalDataError(ValueError):
    """Raised when an external (non-fire) dataset cannot be retrieved."""


class UnknownLayerError(ValueError):
    """Raised when a GeoPackage layer does not correspond to a configured feed."""

    def __init__(self, layer_name: str, path: pathlib.Path) -> None:
        """Identify the unrecognized layer and its source file in the error.

        Args:
            layer_name: The layer that does not match a configured feed.
            path: The GeoPackage containing that layer.
        """
        super().__init__(
            f"layer {layer_name} in {path} does not correspond to a configured feed",
        )
