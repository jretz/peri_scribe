"""Replace pyproj dependencies with controlled test doubles."""

from __future__ import annotations

import pyproj
import pyproj.exceptions


class FailingTransformer:
    """Transformer stand-in whose corner transforms always fail."""

    @staticmethod
    def transform(longitude: float, latitude: float) -> tuple[float, float]:
        """Simulate a projection failure at the requested coordinate.

        Args:
            longitude: Longitude in degrees for the simulated coordinate conversion.
            latitude: Latitude in degrees for the simulated coordinate conversion.

        Raises:
            pyproj.exceptions.ProjError: Always, to exercise coordinate-domain fallback.
        """
        message = f"transform failed at ({longitude}, {latitude})"
        raise pyproj.exceptions.ProjError(message)


def failing_from_crs(
    crs_from: str,
    crs_to: pyproj.CRS,
    *,
    always_xy: bool = True,
) -> FailingTransformer:
    """Provide a transformer that exercises projection failure handling.

    Args:
        crs_from: Source coordinate reference accepted by the transformer factory.
        crs_to: Destination coordinate reference accepted by the transformer factory.
        always_xy: Axis-order option accepted for transformer compatibility.

    Returns:
        A transformer whose coordinate conversions raise projection errors.
    """
    return FailingTransformer()
