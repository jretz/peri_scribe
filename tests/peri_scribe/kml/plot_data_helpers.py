"""Provide data builders and stand-ins for plot data tests."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import pint
    import shapely


def make_perimeter_measurement_recorder(
    *,
    calls: list[shapely.Geometry | None],
    original: typing.Callable[..., pint.Quantity[float] | None],
) -> typing.Callable[..., pint.Quantity[float] | None]:
    """Create a callback with controlled dependencies.

    Count perimeter measurements while preserving their real results.

    Args:
        calls: Shared list recording dependency calls for assertions.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def counting_measure(
        geometry: shapely.Geometry | None,
    ) -> pint.Quantity[float] | None:
        """Count perimeter measurements while preserving their real results.

        Args:
            geometry: Geometry supplied for the selected spatial case.

        Returns:
            The measured exterior perimeter, or None for unusable geometry.
        """
        calls.append(geometry)
        return original(geometry)

    return counting_measure
