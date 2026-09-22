"""HTML balloons describing a fire and its map images."""

from __future__ import annotations

import functools
import html

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
    return html.escape(value, quote=False)


@functools.cache
def description_html(
    description: peri_scribe.presentation.descriptions.FireDescription,
    image_filenames: tuple[str, ...] = (),
    leading_rows: tuple[tuple[str, str | None], ...] = (),
) -> str:
    """Return *description* as the HTML KML balloon text.

    The text is wrapped in a CDATA section so the HTML tags it contains survive as
    markup rather than being read as KML text. Each of *image_filenames* is shown below
    the table as an image whose source is a file stored beside the KML in the KMZ
    archive. Each row in *leading_rows* opens the table above *description*'s own rows,
    so a growth ring's balloon can lead with the area that ring added to the fire before
    the fire's shared facts; a row whose value is missing shows two hyphens, like the
    fire's own rows.

    The balloon is cached by its inputs: the same fire's balloon is embedded in every
    placemark that draws the fire and is rebuilt for each folder view that shows it, and
    a fire's description, image filenames, and added-area rows are identical across
    those placemarks and views.

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
        f'<br/><img src="{html.escape(filename, quote=True)}" />'
        for filename in image_filenames
    )
    return "<![CDATA[" + "".join(parts) + "]]>"
