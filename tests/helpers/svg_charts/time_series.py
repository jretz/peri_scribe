"""Inspect plot drawing behavior with shared test utilities."""

from __future__ import annotations

import defusedxml.minidom


def plot_legend(content: bytes) -> tuple[tuple[str, str, str], ...]:
    """Check legend meaning and styling through the rendered SVG contract.

    Args:
        content: A rendered chart containing a legend.

    Returns:
        Legend labels, stroke colors, and dash patterns in display order.
    """
    drawing = defusedxml.minidom.parseString(content)
    legend = next(
        group
        for group in drawing.getElementsByTagName("g")
        if group.getElementsByTagName("line") and group.getElementsByTagName("text")
    )
    return tuple(
        (
            label.firstChild.data,
            swatch.getAttribute("stroke"),
            swatch.getAttribute("stroke-dasharray"),
        )
        for label, swatch in zip(
            legend.getElementsByTagName("text"),
            legend.getElementsByTagName("line"),
            strict=True,
        )
    )
