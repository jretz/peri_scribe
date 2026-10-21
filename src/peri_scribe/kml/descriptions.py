"""HTML balloons describing a fire and its map images.

Design notes:
[Output serialization](../../../docs/algorithms/output-serialization.md).
"""

from __future__ import annotations

import dataclasses
import html

import document_text.encoding
import peri_scribe.execution
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


@dataclasses.dataclass(frozen=True, kw_only=True)
class BalloonBody:
    """Share escaped common rows at either starting parity and escaped image markup."""

    rows: tuple[str, str]
    images: str


def escaped_cells(rows: tuple[tuple[str, str | None], ...]) -> tuple[str, ...]:
    """Escape source values once before wrapping rows with alternating backgrounds.

    Args:
        rows: Ordered source labels and values, with absent values shown as hyphens.

    Returns:
        Generated cell markup whose source text cannot add document structure.
    """
    return tuple(
        f"<td><b>{escape_html_text(label)}</b></td>"
        f"<td>{escape_html_text('--' if value is None else value)}</td>"
        for label, value in rows
    )


def table_rows(cells: tuple[str, ...], parity: int) -> str:
    """Preserve row alternation when shared cells follow a variable-length prefix.

    Args:
        cells: Generated markup for every row's already escaped cells.
        parity: Number of preceding rows modulo two.

    Returns:
        Complete rows with every globally even row shaded.
    """
    return "".join(
        f"<tr{background}>{row}</tr>"
        for index, row in enumerate(cells, start=parity)
        for background in (
            f' style="background-color:{ALT_ROW_BACKGROUND_COLOR};"'
            if index % 2 == 0
            else "",
        )
    )


def common_body(
    description: peri_scribe.presentation.descriptions.FireDescription,
    image_filenames: tuple[str, ...],
) -> BalloonBody:
    """Share common formatting and escaping across a fire's balloon variants.

    Args:
        description: The fire facts retained unchanged during publication rendering.
        image_filenames: Relative plot filenames in display order.

    Returns:
        Both row parities and the image suffix, retained only in the current execution.
    """
    key = ("balloon_body", description, image_filenames, ALT_ROW_BACKGROUND_COLOR)
    previous = peri_scribe.execution.get(peri_scribe.execution.Group.PRESENTATION, key)
    if isinstance(previous, BalloonBody):
        return previous
    cells = escaped_cells(
        tuple(peri_scribe.presentation.descriptions.description_rows(description)),
    )
    body = BalloonBody(
        rows=(table_rows(cells, 0), table_rows(cells, 1)),
        images="".join(
            f'<br/><img src="{escaped}" />'
            for filename in image_filenames
            for escaped in (html.escape(document_text.encoding.normalized(filename)),)
        ),
    )
    peri_scribe.execution.put(peri_scribe.execution.Group.PRESENTATION, key, body)
    return body


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

    Whole-fire and growth-ring variants share escaped common facts and image markup.
    Identical balloons are reused across folder views within the publication execution.
    Scope exit releases every retained body and balloon; standalone calls retain none.

    Args:
        description: The fire's latest state.
        image_filenames: The relative filename of each plot image to show, in display
            order.
        leading_rows: The (label, value) rows to show at the top of the table, in
            display order.

    Returns:
        The balloon's KML description text.
    """
    key = (
        "balloon_html",
        description,
        image_filenames,
        leading_rows,
        BODY_FONT_SIZE.magnitude,
        ALT_ROW_BACKGROUND_COLOR,
    )
    previous = peri_scribe.execution.get(peri_scribe.execution.Group.PRESENTATION, key)
    if isinstance(previous, document_text.encoding.CData):
        return previous
    body = common_body(description, image_filenames)
    prefix = table_rows(escaped_cells(leading_rows), 0)
    body_style = f' style="font-size:{BODY_FONT_SIZE.magnitude}px;"'
    balloon = document_text.encoding.CData(
        f'<table cellspacing="0" cellpadding="4"{body_style}>'
        + prefix
        + body.rows[len(leading_rows) % 2]
        + "</table>"
        + body.images,
    )
    peri_scribe.execution.put(peri_scribe.execution.Group.PRESENTATION, key, balloon)
    return balloon
