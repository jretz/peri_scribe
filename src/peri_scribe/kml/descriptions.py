"""HTML balloons describing a fire and its map images.

Design notes:
[Output serialization](../../../docs/algorithms/output-serialization.md).
"""

from __future__ import annotations

import functools
import html

import document_text.encoding
import peri_scribe.presentation.descriptions
from measurement_units import units


ALT_ROW_BACKGROUND_COLOR = "#EEF3F8"
BODY_FONT_SIZE = 14 * units.pixels
ADDED_AREA_LABEL = "Added area"


def escape_html_text(value: str) -> str:
    """Escape *value* for safe display inside the balloon's HTML.

    Args:
        value: The text to escape.

    Returns:
        The text with HTML-significant characters escaped.
    """
    return html.escape(document_text.encoding.normalized(value), quote=False)


@functools.cache
def description_html(
    description: peri_scribe.presentation.descriptions.FireDescription,
    image_filenames: tuple[str, ...] = (),
    leading_rows: tuple[tuple[str, str | None], ...] = (),
) -> document_text.encoding.CData:
    """Return *description* as HTML for a KML balloon.

    CDATA keeps the HTML markup intact inside KML. Images listed in *image_filenames*
    appear below the table and refer to files stored beside the KML document in the KMZ
    archive. The optional *leading_rows* let a growth ring show its added area before
    the fire's shared facts. Missing values appear as two hyphens throughout the table.

    Whole-fire placemarks share a balloon. Each growth ring adds its own area row, and
    that ring's balloon is reused across folder views. Caching by all of these inputs
    avoids rebuilding identical balloons while keeping different rings' added areas
    separate.

    Args:
        description: The fire's latest state.
        image_filenames: The relative filename of each plot image to show, in display
            order.
        leading_rows: The (label, value) rows to show at the top of the table, in
            display order.

    Returns:
        The balloon's KML description text.
    """
    body_style = f' style="font-size:{BODY_FONT_SIZE.magnitude}px;"'
    parts = [f'<table cellspacing="0" cellpadding="4"{body_style}>']
    rows = [
        *leading_rows,
        *peri_scribe.presentation.descriptions.description_rows(description),
    ]
    for index, (label, value) in enumerate(rows):
        background = (
            f' style="background-color:{ALT_ROW_BACKGROUND_COLOR};"'
            if index % 2 == 0
            else ""
        )
        parts.append(
            f"<tr{background}><td><b>{escape_html_text(label)}</b></td>"
            f"<td>{escape_html_text('--' if value is None else value)}</td></tr>",
        )
    parts.append("</table>")
    parts.extend(
        f'<br/><img src="{escaped}" />'
        for filename in image_filenames
        for escaped in [html.escape(document_text.encoding.normalized(filename))]
    )
    return document_text.encoding.CData("".join(parts))
