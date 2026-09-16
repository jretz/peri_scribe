"""Tests for peri_scribe.report.gathering."""

from __future__ import annotations

import datetime
import pathlib
import tempfile

import hypothesis

import peri_scribe.report.gathering
import tests.helpers.factories.peri_scribe.report.gathering
import tests.helpers.reference.peri_scribe.report.gathering
import tests.helpers.strategies.peri_scribe.report.gathering


@hypothesis.given(
    sections=tests.helpers.strategies.peri_scribe.report.gathering.report_sections(),
)
def test_report_details_preserves_the_first_entry_for_each_distinct_fire(
    sections: list[tuple[peri_scribe.report.gathering.FireReportEntry, ...]],
) -> None:
    entries = [entry for section in sections for entry in section]
    representatives = [
        entry
        for index, entry in enumerate(entries)
        if not any(
            tests.helpers.reference.peri_scribe.report.gathering.same_report_fire(
                entry,
                previous,
            )
            for previous in entries[:index]
        )
    ]
    expected = sorted(
        representatives,
        key=lambda entry: (entry.name.casefold(), entry.name, entry.identifier or ""),
    )
    assert peri_scribe.report.gathering.report_details(*sections) == tuple(expected)


@hypothesis.given(names=hypothesis.infer)
def test_located_entries_accepts_an_iterator_like_a_list(names: list[str]) -> None:
    fires = [
        tests.helpers.factories.peri_scribe.report.gathering.make_fire(
            name,
            f"id-{index}",
        )
        for index, name in enumerate(names)
    ]
    now = datetime.datetime(2026, 8, 2, tzinfo=datetime.UTC)
    with tempfile.TemporaryDirectory() as directory:
        year_directory = pathlib.Path(directory)
        expected = peri_scribe.report.gathering.located_entries(
            fires,
            {},
            {},
            now,
            year_directory,
        )
        actual = peri_scribe.report.gathering.located_entries(
            iter(fires),
            {},
            {},
            now,
            year_directory,
        )
    assert actual == expected
