"""Source text cannot become report structure or displace another field's evidence."""

import pytest

import peri_scribe.report.markdown
import tests.helpers.factories.document_text


@pytest.mark.parametrize(
    "value",
    [
        "North | South",
        "North\nSouth",
        "[North](https://example.test)",
        "<b>North</b>",
        "\u00a0",
        "\u2003",
        "\u2009",
        "\u2028",
        "\u2029",
    ],
)
def test_markdown_table_lines_preserves_literal_cells(value: str) -> None:
    source = "\n".join(
        peri_scribe.report.markdown.markdown_table_lines(
            ("Fire", "Area"),
            ((value, "100 acres"),),
        ),
    )
    root = tests.helpers.factories.document_text.markdown_root(source)
    rows = root.findall(".//tbody/tr")
    assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
        [value, "100 acres"],
    ]
    assert all(not list(cell) for cell in rows[0])


def test_markdown_table_lines_normalizes_next_line_without_losing_its_cell() -> None:
    source = "\n".join(
        peri_scribe.report.markdown.markdown_table_lines(
            ("Fire", "Area"),
            (("\x85", "100 acres"),),
        ),
    )
    root = tests.helpers.factories.document_text.markdown_root(source)
    assert ["".join(cell.itertext()) for cell in root.findall(".//tbody/tr/td")] == [
        "\n",
        "100 acres",
    ]


@pytest.mark.parametrize(
    "value",
    ["North | South", "**North**", "North\n### South", ""],
)
def test_markdown_text_preserves_name_and_generated_detail_link(value: str) -> None:
    source = peri_scribe.report.markdown.markdown_text(
        tests.helpers.factories.document_text.report(value),
        2026,
    )
    root = tests.helpers.factories.document_text.markdown_root(source)
    links = root.findall(".//a[@href='#fire-detail:0']")
    assert ["".join(link.itertext()) for link in links] == [value]
    assert ["".join(heading.itertext()) for heading in root.findall("h3")] == [value]
