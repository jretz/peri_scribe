"""Tests for peri_scribe.kml.descriptions."""

from __future__ import annotations

import defusedxml.ElementTree as DefusedElementTree
import hypothesis
import hypothesis.strategies

import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions
import tests.helpers.strategies.peri_scribe.presentation.descriptions


@hypothesis.given(
    note=tests.helpers.strategies.peri_scribe.presentation.descriptions.balloon_text(),
    leading_rows=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            tests.helpers.strategies.peri_scribe.presentation.descriptions.balloon_text(),
            hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                tests.helpers.strategies.peri_scribe.presentation.descriptions.balloon_text(),
            ),
        ),
        max_size=5,
    ),
    filenames=hypothesis.strategies.lists(
        tests.helpers.strategies.peri_scribe.presentation.descriptions.balloon_text(),
        max_size=3,
    ),
)
def test_description_html_preserves_text_through_kml_and_html_parsing(
    note: str,
    leading_rows: list[tuple[str, str | None]],
    filenames: list[str],
) -> None:
    image_filenames = tuple(f"plot-{filename}.svg" for filename in filenames)
    encoded = peri_scribe.kml.descriptions.description_html(
        peri_scribe.presentation.descriptions.FireDescription(of_note=note),
        image_filenames,
        tuple(leading_rows),
    )
    kml = DefusedElementTree.fromstring(f"<description>{encoded}</description>")
    balloon = DefusedElementTree.fromstring(f"<balloon>{kml.text}</balloon>")
    rows = [
        tuple("".join(cell.itertext()) for cell in row.findall("td"))
        for row in balloon.findall("table/tr")
    ]
    assert rows[: len(leading_rows)] == [
        (label, "--" if value is None else value) for label, value in leading_rows
    ]
    assert rows[-1] == ("Of note", note)
    assert [element.get("src") for element in balloon.findall("img")] == list(
        image_filenames,
    )
