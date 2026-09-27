"""Parse emitted documents so text assertions observe the reader's actual structure."""

from __future__ import annotations

import typing

import defusedxml.ElementTree as DefusedElementTree
import markdown_it

import peri_scribe.report.gathering
import tests.helpers.factories.peri_scribe.report.markdown


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def markdown_root(source: str) -> ET.Element:
    """Expose real Markdown table and inline parsing to artifact assertions.

    Args:
        source: The emitted Markdown document or fragment.

    Returns:
        The generated HTML inside a single parseable root element.
    """
    rendered = (
        markdown_it
        .MarkdownIt("commonmark", {"html": True})
        .enable("table")
        .render(
            source,
        )
    )
    return DefusedElementTree.fromstring(f"<root>{rendered}</root>")


def report(value: str) -> peri_scribe.report.gathering.FireReport:
    """Put the same source text into independently serialized report fields.

    Args:
        value: Source-provided fire name, identifier, and location text.

    Returns:
        A complete report with one identifiable fire and a numerical fact beside it.
    """
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        value,
        identifier=value,
        location=value,
        area=100,
        score=1,
    )
    return peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(entry,),
        fire_details=(entry,),
    )
