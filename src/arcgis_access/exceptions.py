"""Exceptions raised for unusable ArcGIS query results."""


class NoFeaturesError(ValueError):
    """Raised when a layer returns no features."""


class NoSpatialReferenceError(ValueError):
    """Raised when a layer's spatial reference cannot be determined."""

    def __init__(self, message: str = "no usable spatial reference wkid") -> None:
        """Preserve the reason a spatial reference could not be selected.

        Args:
            message: The explanation to include in the error.
        """
        super().__init__(message)
