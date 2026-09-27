"""Published documents retain complete contents through interrupted serialization."""

import json
import pathlib

import pytest

import peri_scribe.models
import peri_scribe.output
import tests.helpers.doubles.peri_scribe.document_publication
import tests.helpers.factories.peri_scribe.output


def test_write_document_preserves_previous_json_after_interruption(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "index.json"
    original = '{"version": "previous", "fires": []}'
    path.write_text(original)
    document = peri_scribe.models.FireIndex(version="current", fires=[])
    monkeypatch.setattr(
        json,
        "dump",
        tests.helpers.doubles.peri_scribe.document_publication.interrupt_json,
    )
    with pytest.raises(
        tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss,
    ):
        peri_scribe.output.write_document(path, document)
    assert path.read_text() == original


def test_write_fire_scores_ccdf_preserves_previous_page_after_interruption(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "scores.html"
    original = "<!DOCTYPE html><html>Previous page</html>"
    path.write_text(original)
    monkeypatch.setattr(
        pathlib.Path,
        "write_text",
        tests.helpers.doubles.peri_scribe.document_publication.interrupt_text,
    )
    with pytest.raises(
        tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss,
    ):
        peri_scribe.output.write_fire_scores_ccdf(
            path,
            tests.helpers.factories.peri_scribe.output.fire_scores_document([12]),
        )
    assert path.read_text() == original
