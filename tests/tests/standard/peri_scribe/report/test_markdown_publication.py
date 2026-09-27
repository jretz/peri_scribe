"""Interrupted rendering retains the complete previously published report."""

import pathlib

import pytest

import peri_scribe.paths
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.helpers.doubles.peri_scribe.document_publication


def test_render_markdown_report_preserves_previous_report_after_interruption(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "2026"
    path = peri_scribe.paths.markdown_report_path(directory)
    path.parent.mkdir(parents=True)
    original = "# Previous complete report\n"
    path.write_text(original)
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )
    monkeypatch.setattr(
        pathlib.Path,
        "write_text",
        tests.helpers.doubles.peri_scribe.document_publication.interrupt_text,
    )
    with pytest.raises(
        tests.helpers.doubles.peri_scribe.document_publication.ProcessLoss,
    ):
        peri_scribe.report.markdown.render_markdown_report(report, directory)
    assert path.read_text() == original
