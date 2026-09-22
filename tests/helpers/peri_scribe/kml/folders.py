"""Inspect folders behavior with shared test utilities."""

from __future__ import annotations

import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions


def balloon_text(
    description: peri_scribe.presentation.descriptions.FireDescription,
    image_filenames: tuple[str, ...] = (),
    leading_rows: tuple[tuple[str, str | None], ...] = (),
) -> str:
    """Return *description*'s balloon as the KML parser reads it.

    Args:
        description: The fire description to render.
        image_filenames: The plot image filenames to show below the table.
        leading_rows: The rows to lead the table with.

    Returns:
        The balloon's CDATA content, without the section markers the parser strips.
    """
    html = peri_scribe.kml.descriptions.description_html(
        description,
        image_filenames,
        leading_rows=leading_rows,
    )
    return html[len("<![CDATA[") : -len("]]>")]
