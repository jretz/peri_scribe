"""Inspect colormap behavior with shared test utilities."""

from __future__ import annotations

import peri_scribe.kml.colormap


def tick_labels(strip: str) -> dict[int, int]:
    """Return each row's index and the tick label printed to its left.

    Args:
        strip: The colormap strip.

    Returns:
        The labelled rows' indices mapped to the values printed on them.
    """
    labels = {}
    for index, line in enumerate(strip.splitlines()):
        text = line.split("\x1b", 1)[0].strip()
        if text:
            labels[index] = int(text)
    return labels


def range_labels(strip: str) -> dict[int, int]:
    """Return each row's index and the used-range label printed to its right.

    Args:
        strip: The colormap strip.

    Returns:
        The labelled rows' indices mapped to the values printed on them.
    """
    labels = {}
    for index, line in enumerate(strip.splitlines()):
        suffix = line.rsplit(peri_scribe.kml.colormap.ANSI_RESET, 1)[-1]
        text = suffix.replace(peri_scribe.kml.colormap.USED_RANGE_MARKER, "").strip()
        if text:
            labels[index] = int(text)
    return labels
