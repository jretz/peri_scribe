"""Exception classes for peri_scribe."""

import pathlib


class NoFeaturesError(ValueError):
    """Raised when a feed returns no features."""


class FeedFetchError(ValueError):
    """Raised when a configured feed cannot be fetched."""


class AdministrativeBoundariesError(ValueError):
    """Raised when administrative boundary data cannot be produced."""


class ExternalDataError(ValueError):
    """Raised when an external (non-fire) dataset cannot be retrieved."""


class NoSpatialReferenceError(ValueError):
    """Raised when a layer's spatial reference cannot be determined."""

    def __init__(self, message: str = "no usable spatial reference wkid") -> None:
        super().__init__(message)


class UnknownLayerError(ValueError):
    """Raised when a GeoPackage layer does not correspond to a configured feed."""

    def __init__(self, layer_name: str, path: pathlib.Path) -> None:
        super().__init__(
            f"layer {layer_name} in {path} does not correspond to a configured feed",
        )
