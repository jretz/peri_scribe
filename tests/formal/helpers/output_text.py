"""Bind the checked text codec to serialized Markdown, XML, HTML, and KMZ artifacts."""

from __future__ import annotations

import functools
import itertools
import pathlib
import typing
import zipfile

import defusedxml.ElementTree as DefusedElementTree
import shapely

import document_text.encoding
import kml_io.geometry
import kml_io.kmz
import peri_scribe.kml.descriptions
import peri_scribe.presentation.descriptions
import peri_scribe.report.markdown
import tests.formal.helpers.oracle
import tests.helpers.factories.document_text
import tests.helpers.peri_scribe.kml.parsing


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def catalogue() -> tuple[str, ...]:
    """Cross syntax fragments independently of the production escape tables.

    Returns:
        Scalar boundaries, complete markup lookalikes, and short structural mixtures.
    """
    scalars = (
        *range(160),
        0xA0,
        0x1680,
        *range(0x2000, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0xD7FF,
        0xD800,
        0xDFFF,
        0xE000,
        0xFFFD,
        0xFFFE,
        0xFFFF,
        0x10000,
        0x10FFFF,
    )
    examples = (
        "",
        " ",
        "  North  ",
        "\r\n",
        "\r\r\n",
        "North | South",
        "North\n### South",
        "[North](https://example.test)",
        "![image](x.png)",
        "<a id='fire-detail:0'>North</a>",
        "<![CDATA[North]]>",
        "]]>]]>]]>",
        "&#124; &amp; &lt;",
        "Café 日本 🔥",
        "a\u2028b\u2029c",
        "e\u0301",
        "North #",
        "---",
        "~~~",
    )
    return tuple(
        dict.fromkeys((
            *examples,
            *(chr(value) for value in scalars),
            *(f"North{chr(value)}South" for value in scalars),
            *(
                "".join(parts)
                for parts in itertools.product(
                    ("A", "|", "\n", "[", "]", "<", "&", "*"),
                    repeat=3,
                )
            ),
        )),
    )


def command(operation: str, value: str) -> str:
    """Transport raw code points without imposing a second normalization policy.

    Args:
        operation: The proved executable transformation to evaluate.
        value: Raw source text, including unsupported scalar values.

    Returns:
        An ASCII-only oracle request that safely carries surrogate code points.
    """
    return operation + "|" + " ".join(str(ord(character)) for character in value)


def expected(operation: str, values: tuple[str, ...]) -> list[str]:
    """Decode only the compiled oracle's emitted code points.

    Args:
        operation: The normalization or encoding operation.
        values: Source strings in fixture order.

    Returns:
        Exactly the strings computed by the checked Lean definitions.
    """
    return [
        "".join(chr(value) for value in row)
        for row in tests.formal.helpers.oracle.evaluate(
            [command(operation, value) for value in values],
            executable="oracleOutputText",
        )
    ]


def check_encodings() -> None:
    """Check exact encodings and parser preservation for every catalogue row."""
    values = catalogue()
    normalized = expected("normalize", values)
    markdown = expected("markdown", values)
    xml = expected("xml", values)
    cdata = expected("cdata", values)
    for source, plain, encoded_markdown, encoded_xml, encoded_cdata in zip(
        values,
        normalized,
        markdown,
        xml,
        cdata,
        strict=True,
    ):
        assert document_text.encoding.normalized(source) == plain
        assert document_text.encoding.markdown(source) == encoded_markdown, (
            "source text encoding disagrees with checked reference"
        )
        assert document_text.encoding.xml(source) == encoded_xml
        element = DefusedElementTree.fromstring(f"<text>{encoded_xml}</text>")
        assert "".join(element.itertext()) == plain
        assert not list(element)
        trusted = document_text.encoding.CData(source)
        assert str(trusted) == encoded_cdata
        element = DefusedElementTree.fromstring(f"<text>{trusted}</text>")
        assert "".join(element.itertext()) == plain
        assert not list(element)
        source_table = "\n".join(
            peri_scribe.report.markdown.markdown_table_lines(
                ("Source", "Evidence"),
                ((source, "100 acres"),),
            ),
        )
        root = tests.helpers.factories.document_text.markdown_root(source_table)
        rows = root.findall(".//tbody/tr")
        assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
            [plain, "100 acres"],
        ]
        assert all(not list(cell) for cell in rows[0])


def row_structure(rows: list[ET.Element]) -> tuple[int, ...]:
    """Observe row and cell boundaries independently of the writer's strings.

    Args:
        rows: Table rows found in the parsed artifact.

    Returns:
        The formal framing tokens for exactly the parser's observed cells.
    """
    return tuple(
        marker
        for row in rows
        for marker in (3, *(value for _cell in row for value in (1, 2)), 4)
    )


def write_document(source: str, stream: typing.TextIO) -> None:
    """Use real KML roles and a real generated balloon within a real archive.

    Args:
        source: Text shared by the document name, folder, point, and evidence fields.
        stream: The archive writer's actual UTF-8 document member.
    """
    writer = kml_io.geometry.KmlWriter(stream)
    balloon = peri_scribe.kml.descriptions.description_html(
        peri_scribe.presentation.descriptions.FireDescription(identifier=source),
        ("plot.png",),
        leading_rows=((source, source),),
    )
    with (
        writer.document(source, ('<Style id="fire"/>',), description=source),
        writer.folder(source),
    ):
        kml_io.geometry.point_placemark(
            writer,
            source,
            "#fire",
            shapely.Point(-120, 35),
            1,
            description=balloon,
        )


def check_artifacts(directory: pathlib.Path) -> None:
    """Compare complete saved reports and archives with the checked text contract.

    Args:
        directory: Isolated root for all publication artifacts.
    """
    values = catalogue()
    normalized = expected("normalize", values)
    frame = tests.formal.helpers.oracle.evaluate(
        ["rows|3 2 2 2"],
        executable="oracleOutputText",
    )[0]
    for index, (source, plain) in enumerate(zip(values, normalized, strict=True)):
        year = directory / str(index) / "2026"
        path = peri_scribe.report.markdown.render_markdown_report(
            tests.helpers.factories.document_text.report(source),
            year,
        )
        root = tests.helpers.factories.document_text.markdown_root(path.read_text())
        assert ["".join(heading.itertext()) for heading in root.findall("h3")] == [
            plain,
        ]
        links = root.findall(".//a[@href]")
        assert [(link.get("href"), "".join(link.itertext())) for link in links] == [
            ("#fire-detail:0", plain),
        ]
        assert [element.get("id") for element in root.findall(".//*[@id]")] == [
            "fire-detail:0",
        ]
        rows = root.findall(".//tbody/tr")
        assert row_structure(rows) == frame
        assert [["".join(cell.itertext()) for cell in row] for row in rows] == [
            [plain, plain, "100 acres"],
            ["Location", plain],
            ["Area", "100 acres"],
            ["Identifier", plain],
        ]
        assert not root.findall(".//script")
        check_archive(year, source, plain)


def check_archive(year: pathlib.Path, source: str, plain: str) -> None:
    """Check the saved archive and its decoded balloon without replacing renderers.

    Args:
        year: Isolated directory for the actual KMZ file.
        source: Original fixture text before encoding.
        plain: Normalized content returned by the compiled Lean oracle.
    """
    tag = tests.helpers.peri_scribe.kml.parsing.kml_tag
    archive = year / "fire.kmz"
    kml_io.kmz.write_kmz(
        archive,
        functools.partial(write_document, source),
        {"plot.png": b"image"},
    )
    with zipfile.ZipFile(archive) as contents:
        document = tests.helpers.peri_scribe.kml.parsing.document_from(
            contents.read("doc.kml").decode(),
        )
        assert contents.namelist() == ["doc.kml", "plot.png"]
        assert contents.read("plot.png") == b"image"
    assert ["".join(name.itertext()) for name in document.iter(tag("name"))] == [
        plain,
        plain,
        plain,
    ]
    description = document.find(tag("description"))
    assert description is not None
    assert "".join(description.itertext()) == plain
    placemarks = document.findall(f".//{tag('Placemark')}")
    assert len(placemarks) == 1
    balloon = placemarks[0].findtext(tag("description"))
    assert balloon is not None
    html = DefusedElementTree.fromstring(f"<root>{balloon}</root>")
    balloon_rows = html.findall(".//tr")
    assert ["".join(cell.itertext()) for cell in balloon_rows[0]] == [plain, plain]
    identifier = next(
        row for row in balloon_rows if "".join(row[0].itertext()) == "Identifier"
    )
    assert "".join(identifier[1].itertext()) == plain
    assert all(len(row) == len(("label", "value")) for row in balloon_rows)
    assert [image.get("src") for image in html.findall("img")] == ["plot.png"]
    assert not html.findall(".//a")
