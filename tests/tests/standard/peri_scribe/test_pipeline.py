"""Pipeline operations preserve command selection, recovery, and publication."""

from __future__ import annotations

import datetime
import pathlib
import typing

import click
import pytest

import peri_scribe.pipeline
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import peri_scribe.sources.catalog
import peri_scribe.sources.digests
import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import tests.helpers.doubles.peri_scribe.main_run
import tests.helpers.doubles.peri_scribe.main_source
import tests.helpers.doubles.peri_scribe.main_write_reports
import tests.helpers.factories.peri_scribe.sources.snapshots
from measurement_units import units


if typing.TYPE_CHECKING:
    import structlog.testing


def test_stored_evacuations_digest_uses_evacuations_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = pathlib.Path("/data/2026/sources/evacuations.gpkg")
    monkeypatch.setattr(
        peri_scribe.sources.external_data,
        "output_path",
        lambda _year_directory, _source: output,
    )
    digests: list[tuple[pathlib.Path, str]] = []

    stored_geopackage_digest = (
        tests.helpers.doubles.peri_scribe.main_run.make_digest_recorder(
            digests=digests,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.digests,
        "stored_geopackage_digest",
        stored_geopackage_digest,
    )
    result = peri_scribe.pipeline.stored_evacuations_digest(pathlib.Path("/data/2026"))
    assert result == "digest"
    assert digests == [(output, "evacuations")]


def test_duration_convert_whole_hours_and_days() -> None:
    duration = peri_scribe.pipeline.Duration()
    assert duration.convert("0h", None, None) == datetime.timedelta(0)
    assert duration.convert("12h", None, None) == datetime.timedelta(hours=12)
    assert duration.convert("24h", None, None) == datetime.timedelta(hours=24)
    assert duration.convert("1d", None, None) == datetime.timedelta(days=1)
    assert duration.convert("3d", None, None) == datetime.timedelta(days=3)
    assert duration.convert("0d", None, None) == datetime.timedelta(0)


def test_duration_convert_accepts_an_already_converted_timedelta() -> None:
    duration = peri_scribe.pipeline.Duration()
    value = datetime.timedelta(hours=12)
    assert duration.convert(value, None, None) is value


@pytest.mark.parametrize("value", [None, 12, b"12h"])
def test_duration_convert_rejects_values_that_are_not_duration_text(
    value: object,
) -> None:
    duration = peri_scribe.pipeline.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert(value, None, None)


def test_duration_convert_rejects_out_of_range_durations() -> None:
    duration = peri_scribe.pipeline.Duration()
    with pytest.raises(click.BadParameter):
        duration.convert("9999999999999h", None, None)


def test_fetch_external_source_uses_given_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
) -> None:
    source = peri_scribe.sources.catalog.BUILDINGS_SOURCE
    year_directory = pathlib.Path("data/2026")
    fetched: list[tuple[object, pathlib.Path]] = []

    fetch_external_source = (
        tests.helpers.doubles.peri_scribe.main_source.make_fetch_recorder(
            fetched=fetched,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.pipeline.fetch_external_source(source, year_directory)
    assert fetched == [(source, year_directory)]
    fetched_entry = next(
        entry
        for entry in log_output.entries
        if entry["event"] == "Fetched external source"
    )
    assert fetched_entry["paths"] == ["/out.gpkg"]


def test_fetch_external_source_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    current_year: typing.Iterator[None],
) -> None:
    source = peri_scribe.sources.catalog.EVACUATIONS_SOURCE
    fetched: list[tuple[object, pathlib.Path]] = []

    fetch_external_source = (
        tests.helpers.doubles.peri_scribe.main_source.make_fetch_recorder(
            fetched=fetched,
        )
    )

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.pipeline.fetch_external_source(source, None)
    assert fetched == [
        (
            source,
            tests.helpers.factories.peri_scribe.sources.snapshots.BASE_DIRECTORY
            / "data"
            / "2026",
        ),
    ]


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

    gather_report = (
        tests.helpers.doubles.peri_scribe.main_write_reports.make_report_gatherer(
            gathered=gathered,
            report=report,
        )
    )

    render_markdown_report = (
        tests.helpers.doubles.peri_scribe.main_write_reports.make_report_renderer(
            rendered=rendered,
            output=output,
        )
    )

    monkeypatch.setattr(peri_scribe.report.gathering, "gather_report", gather_report)
    monkeypatch.setattr(
        peri_scribe.report.markdown,
        "render_markdown_report",
        render_markdown_report,
    )

    result = peri_scribe.pipeline.write_reports(year_directory)

    assert result == output
    assert gathered == [year_directory]
    assert rendered == [(report, year_directory)]


def test_area_convert_accepts_equivalent_explicit_units() -> None:
    parser = peri_scribe.pipeline.Area()
    assert parser.convert("1 hectare", None, None) == 10000 * units.Unit("meters ** 2")
    with pytest.raises(click.BadParameter, match="positive area"):
        parser.convert(object(), None, None)
