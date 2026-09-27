"""Literal source text must survive XML names without acquiring markup privileges."""

import pytest

import tests.helpers.factories.kml_io.geometry
import tests.helpers.peri_scribe.kml.parsing


@pytest.mark.parametrize("value", ["<![CDATA[North]]>", "North\x00South"])
def test_kml_writer_document_preserves_literal_name(value: str) -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    with writer.document(value, ()):
        pass
    document = tests.helpers.peri_scribe.kml.parsing.document_from(writer.text())
    name = document.find(tests.helpers.peri_scribe.kml.parsing.kml_tag("name"))
    assert name is not None
    assert name.text == value.replace("\x00", "\ufffd")
    assert not list(name)
