"""write_reports helper tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.main
import peri_scribe.report.gathering
import peri_scribe.report.markdown


if typing.TYPE_CHECKING:
    import pytest


def test_write_reports_gathers_and_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    year_directory = pathlib.Path("data/2026")
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )
    output = year_directory / "reports" / "PeriScribe Fires 2026.md"
    gathered: list[pathlib.Path] = []
    rendered: list[tuple[peri_scribe.report.gathering.FireReport, pathlib.Path]] = []

    def gather_report(
        directory: pathlib.Path,
    ) -> peri_scribe.report.gathering.FireReport:
        gathered.append(directory)
        return report

    def render_markdown_report(
        gathered_report: peri_scribe.report.gathering.FireReport,
        directory: pathlib.Path,
    ) -> pathlib.Path:
        rendered.append((gathered_report, directory))
        return output

    monkeypatch.setattr(peri_scribe.report.gathering, "gather_report", gather_report)
    monkeypatch.setattr(
        peri_scribe.report.markdown,
        "render_markdown_report",
        render_markdown_report,
    )

    result = peri_scribe.main.write_reports(year_directory)

    assert result == output
    assert gathered == [year_directory]
    assert rendered == [(report, year_directory)]
