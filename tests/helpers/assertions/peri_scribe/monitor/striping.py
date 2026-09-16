"""Inspect complete rendered rows so padding and wrapped lines count toward shading."""

import typing

import pytest
import textual.color
import textual.widget


if typing.TYPE_CHECKING:
    import rich.color


def row_backgrounds(
    widget: textual.widget.Widget,
    metadata: str,
    index: int,
) -> set[rich.color.Color | None]:
    """Collect backgrounds from every cell belonging to a logical row.

    Args:
        widget: The mounted list or hierarchy.
        metadata: Textual's row identity for this widget type.
        index: The logical row to inspect, including any wrapped lines.

    Returns:
        Distinct background colors across the row's text, indentation, and padding.
    """
    return {
        segment.style.bgcolor
        for row in widget.render_lines(widget.size.region)
        for segment in row
        if segment.style is not None and segment.style.meta.get(metadata) == index
    }


def assert_tint_preserves_brightness(
    tinted: set[rich.color.Color | None],
    neutral: set[rich.color.Color | None],
) -> None:
    """Status hues must preserve stripe contrast across text and empty row space.

    Args:
        tinted: Background colors across the status row.
        neutral: Background colors across an ordinary row with the same stripe shade.
    """
    assert len(tinted) == len(neutral) == 1
    assert tinted != neutral
    original_color = textual.color.Color.from_rich_color(next(iter(neutral)))
    tinted_color = textual.color.Color.from_rich_color(next(iter(tinted)))
    assert tinted_color.brightness == pytest.approx(
        original_color.brightness,
        abs=0.5 / 255,
    )
