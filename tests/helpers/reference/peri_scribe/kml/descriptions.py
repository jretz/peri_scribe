"""Keep the original flat balloon layout independent of shared body composition."""

from __future__ import annotations

import html

import document_text.encoding
import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions


def description_html(
    description: peri_scribe.presentation.descriptions.FireDescription,
    image_filenames: tuple[str, ...],
    leading_rows: tuple[tuple[str, str | None], ...],
) -> str:
    """Render every row in one pass without fragment reuse or retained results.

    Args:
        description: Complete fire facts passed to the production formatter.
        image_filenames: Relative image references in display order.
        leading_rows: Arbitrarily many rows preceding the common fire facts.

    Returns:
        The complete original HTML and CDATA wire string.
    """
    size = peri_scribe.kml.descriptions.BODY_FONT_SIZE.magnitude
    parts = [f'<table cellspacing="0" cellpadding="4" style="font-size:{size}px;">']
    rows = [
        *leading_rows,
        *peri_scribe.presentation.descriptions.description_rows(description),
    ]
    for index, (label, value) in enumerate(rows):
        color = peri_scribe.kml.descriptions.ALT_ROW_BACKGROUND_COLOR
        background = f' style="background-color:{color};"' if index % 2 == 0 else ""
        escaped_label = html.escape(
            document_text.encoding.normalized(label),
            quote=False,
        )
        escaped_value = html.escape(
            document_text.encoding.normalized("--" if value is None else value),
            quote=False,
        )
        parts.append(
            f"<tr{background}><td><b>{escaped_label}</b></td>"
            f"<td>{escaped_value}</td></tr>",
        )
    parts.append("</table>")
    for filename in image_filenames:
        escaped = html.escape(document_text.encoding.normalized(filename))
        parts.append(f'<br/><img src="{escaped}" />')
    return str(document_text.encoding.CData("".join(parts)))
