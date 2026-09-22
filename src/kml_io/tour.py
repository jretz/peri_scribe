"""Reveal placemarks through timed Google Earth tour updates."""

from __future__ import annotations

import typing

import kml_io.geometry


if typing.TYPE_CHECKING:
    import pint


def visibility_change(placemark_ids: typing.Sequence[str], shown_through: int) -> str:
    """Describe the entire visibility state so every tour step can be replayed.

    Args:
        placemark_ids: Placemark identifiers in their reveal order.
        shown_through: The index of the last placemark to show.

    Returns:
        Visibility updates for every placemark.
    """
    updates: list[str] = []
    for index, placemark_id in enumerate(placemark_ids):
        visibility = "1" if index <= shown_through else "0"
        updates.append(
            f'<Placemark targetId="{placemark_id}">'
            f"<visibility>{visibility}</visibility>"
            "</Placemark>",
        )
    return "".join(updates)


def reveal_tour(
    writer: kml_io.geometry.KmlWriter,
    name: str,
    placemark_ids: typing.Sequence[str],
    waits: typing.Sequence[pint.Quantity[float]],
    *,
    visible: bool = True,
) -> None:
    """Keep tour serialization independent of the observations that set its timing.

    Args:
        writer: The document's shared writer.
        name: The tour's display name.
        placemark_ids: Placemark identifiers in their reveal order.
        waits: One playback duration after each reveal, including the final frame.
        visible: Whether the tour is initially visible.

    Raises:
        ValueError: The identifiers and waits have different lengths.
    """
    if len(placemark_ids) != len(waits):
        message = "Every tour placemark must have one playback duration"
        raise ValueError(message)
    writer.write("<gx:Tour>")
    if not visible:
        writer.write("<visibility>0</visibility>")
    writer.write(f"<name>{kml_io.geometry.escape_text(name)}</name><gx:Playlist>")
    for index, wait in enumerate(waits):
        writer.write("<gx:AnimatedUpdate><Update><targetHref></targetHref><Change>")
        writer.write(visibility_change(placemark_ids, index))
        writer.write("</Change></Update></gx:AnimatedUpdate>")
        writer.write(
            f"<gx:Wait><gx:duration>{wait.m_as('second')}</gx:duration></gx:Wait>",
        )
    writer.write("</gx:Playlist></gx:Tour>")
