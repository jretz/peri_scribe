"""Tests for peri_scribe.kml_template_reader."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import tests.kml_helpers


def test_placemark_style_urls_descends_into_folders() -> None:
    document = tests.kml_helpers.document_from(peri_scribe.kml_template.template_kml())
    urls = peri_scribe.kml_template_reader.placemark_style_urls(document)
    assert urls["Point Location"] == "#point-icon"
    assert urls["Interior"] == "#perimeter-fill"
    assert urls["Latest Perimeter"] == "#perimeter-outline-1"
    assert urls["Penultimate Perimeter"] == "#perimeter-outline-2"
    assert urls["Antepenultimate Perimeter"] == "#perimeter-outline-3"


def test_collect_placemark_style_urls_skips_placemarks_without_style() -> None:
    document = tests.kml_helpers.document_from(
        """
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Folder>
              <name>Folder</name>
              <Placemark><name>Unstyled</name></Placemark>
              <Placemark><Point/></Placemark>
            </Folder>
          </Document>
        </kml>
        """,
    )
    urls: dict[str, str] = {}
    peri_scribe.kml_template_reader.collect_placemark_style_urls(document, urls)
    assert urls == {}


def test_style_from_requires_style_id() -> None:
    document = tests.kml_helpers.document_from(
        """
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Style/>
          </Document>
        </kml>
        """,
    )
    style_element = document.find(tests.kml_helpers.kml_tag("Style"))
    assert style_element is not None
    with pytest.raises(ValueError, match="no id attribute"):
        peri_scribe.kml_template_reader.style_from(style_element)


def test_template_from_collects_styles_and_style_urls() -> None:
    template = peri_scribe.kml_template_reader.template_from(
        peri_scribe.kml_template.template_kml(),
    )
    assert [style.id for style in template.styles] == [
        "point-icon",
        "perimeter-fill",
        "perimeter-outline-1",
        "perimeter-outline-2",
        "perimeter-outline-3",
        "days-fill-1",
        "days-fill-2",
        "days-fill-3",
        "days-fill-4",
        "days-fill-5",
        "days-fill-6",
        "days-fill-7",
        "days-fill-8",
    ]
    assert template.style_urls["Point Location"] == "#point-icon"


def test_template_from_requires_document() -> None:
    kml_text = '<kml xmlns="http://www.opengis.net/kml/2.2"/>'
    with pytest.raises(ValueError, match="no Document element"):
        peri_scribe.kml_template_reader.template_from(kml_text)


def test_read_template_reads_file(monkeypatch: pytest.MonkeyPatch) -> None:
    text = peri_scribe.kml_template.template_kml()

    def read_text(_self: pathlib.Path, encoding: str) -> str:
        assert encoding == "utf-8"
        return text

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    template = peri_scribe.kml_template_reader.read_template(
        pathlib.Path("/templates/PeriScribe Template.kml"),
    )
    assert (
        template.style_urls
        == peri_scribe.kml_template_reader.template_from(text).style_urls
    )
