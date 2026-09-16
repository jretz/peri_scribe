"""Replace fire data dependencies with controlled test doubles."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import shapely.geometry


def make_added_area_recorder(
    *,
    calls: list[tuple[shapely.geometry.base.BaseGeometry, ...]],
    original: typing.Callable[..., tuple[object, ...]],
) -> typing.Callable[..., tuple[object, ...]]:
    """Create a callback with controlled dependencies.

    Observe added-area calculations while preserving real measurements.

    Args:
        calls: Shared list recording dependency calls for assertions.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def tracked(
        geometries: typing.Iterable[shapely.geometry.base.BaseGeometry],
    ) -> tuple[object, ...]:
        """Observe added-area calculations while preserving real measurements.

        Args:
            geometries: The ordered ring sequence whose cache use is checked.

        Returns:
            The measured added areas from the original implementation.
        """
        values = tuple(geometries)
        calls.append(values)
        return original(values)

    return tracked
