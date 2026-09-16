"""Calculate independent expected results for colormap tests."""

from __future__ import annotations


MAXIMUM_COLOR_CHANNEL_ERROR = 6


def expected_rgb(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    """Return *rgb* on a 0 to 1 scale rounded to 8-bit components.

    Args:
        rgb: The color as (red, green, blue) components from 0 to 1.

    Returns:
        The color as (red, green, blue) components from 0 to 255.
    """
    return (round(rgb[0] * 255), round(rgb[1] * 255), round(rgb[2] * 255))
