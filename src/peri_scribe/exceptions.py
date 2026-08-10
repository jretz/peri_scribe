"""Exception classes for peri_scribe."""


class NoFeaturesError(ValueError):
    """Raised when a feed returns no features."""


class NoSpatialReferenceError(ValueError):
    """Raised when a layer's spatial reference cannot be determined."""

    def __init__(self, message: str = "no usable spatial reference wkid") -> None:
        super().__init__(message)
