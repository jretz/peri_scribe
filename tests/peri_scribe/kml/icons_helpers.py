"""Generate square RGBA images with varied pixel values and dimensions."""

from __future__ import annotations

import hypothesis.strategies


@hypothesis.strategies.composite
def rgba_images(draw: hypothesis.strategies.DrawFn) -> tuple[int, bytes]:
    """Cover row boundaries, transparency, and byte values in custom PNG output.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A positive side length and its tightly packed RGBA pixels.
    """
    side = draw(hypothesis.strategies.integers(1, 24))
    byte_count = side * side * 4
    pixels = draw(
        hypothesis.strategies.binary(min_size=byte_count, max_size=byte_count),
    )
    return side, pixels
