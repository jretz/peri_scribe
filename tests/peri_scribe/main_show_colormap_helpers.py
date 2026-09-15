"""Provide data builders and stand-ins for main show colormap tests."""

from __future__ import annotations

import typing


def recording_renderer(
    calls: list[tuple[int, int]],
    strip: str,
) -> typing.Callable[..., str]:
    """Return a colormap renderer that records each call's trim window.

    Args:
        calls: The list the renderer appends each (trim_start, trim_end) to.
        strip: The text the renderer returns.

    Returns:
        The stand-in renderer.
    """

    def render(*, trim_start: int, trim_end: int) -> str:
        """Capture colormap endpoints before returning the configured strip.

        Args:
            trim_start: Number of colors excluded from the cool end of the Turbo ramp.
            trim_end: Number of colors excluded from the hot end of the Turbo ramp.

        Returns:
            The configured terminal color strip.
        """
        calls.append((trim_start, trim_end))
        return strip

    return render
