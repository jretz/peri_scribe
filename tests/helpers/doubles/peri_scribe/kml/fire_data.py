"""Replace fire data dependencies with controlled test doubles."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import shapely.geometry

    import peri_scribe.presentation.fire_data


def prepared_fires_stub(
    fires: list[peri_scribe.presentation.fire_data.PreparedFire],
) -> typing.Callable[..., list[peri_scribe.presentation.fire_data.PreparedFire]]:
    """Expose optional prepared-history cases at the chart consumer boundary.

    Args:
        fires: Prepared fire facts and their optional histories.

    Returns:
        A preparation replacement returning the supplied fire facts.
    """

    def prepare(
        *args: object,
        **kwargs: object,
    ) -> list[peri_scribe.presentation.fire_data.PreparedFire]:
        """Keep chart tests independent of whether the producer prepares history.

        Args:
            args: Positional preparation inputs.
            kwargs: Additional preparation inputs.

        Returns:
            The fire facts selected by this test.
        """
        return fires

    return prepare


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
