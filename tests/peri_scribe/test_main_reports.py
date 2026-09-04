"""Reports command tests for peri_scribe.main."""

from __future__ import annotations

import datetime
import pathlib
import typing

import pytest

import peri_scribe.main
import peri_scribe.output
import peri_scribe.report.gathering
import peri_scribe.report.markdown
from tests.conftest import CLICK_USAGE_ERROR_EXIT_CODE
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import click.testing


def test_reports_writes_reports_for_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[pathlib.Path] = []
    output = pathlib.Path("data/2026/reports/PeriScribe Fires 2026.md")

    def write_reports(directory: pathlib.Path) -> pathlib.Path:
        calls.append(directory)
        return output

    monkeypatch.setattr(peri_scribe.main, "write_reports", write_reports)

    result = runner.invoke(peri_scribe.main.cli, ["reports", "data/2026"])

    assert result.exit_code == 0
    assert calls == [pathlib.Path("data/2026")]


@pytest.mark.usefixtures("current_year")
def test_report_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[pathlib.Path] = []

    def write_reports(directory: pathlib.Path) -> pathlib.Path:
        calls.append(directory)
        return directory / "reports" / "PeriScribe Fires 2026.md"

    monkeypatch.setattr(peri_scribe.main, "write_reports", write_reports)

    result = runner.invoke(peri_scribe.main.cli, ["reports"])

    assert result.exit_code == 0
    assert calls == [BASE_DIRECTORY / "data" / "2026"]


def test_reports_rejects_missing_directory(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["reports", "no-such-directory"])
    assert result.exit_code == CLICK_USAGE_ERROR_EXIT_CODE
    assert "does not exist" in result.output


def test_reports_help_names_current_year_default(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["reports", "--help"])
    assert result.exit_code == 0
    assert (
        f"{peri_scribe.output.DATA_DIRECTORY}/{datetime.date.today().year}"
    ) in result.output
    assert "data/<current year>" not in result.output


def test_cli_help_lists_reports(
    runner: click.testing.CliRunner,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["--help"])
    assert result.exit_code == 0
    assert "reports" in result.output


def test_write_reports_gathers_and_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("data/2026")
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
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

    monkeypatch.setattr(
        peri_scribe.report.gathering,
        "gather_report",
        gather_report,
    )
    monkeypatch.setattr(
        peri_scribe.report.markdown,
        "render_markdown_report",
        render_markdown_report,
    )

    result = peri_scribe.main.write_reports(year_directory)

    assert result == output
    assert gathered == [year_directory]
    assert rendered == [(report, year_directory)]
