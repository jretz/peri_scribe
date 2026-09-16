"""Area selection follows mapping freshness and actual reporting evidence."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import peri_scribe.areas
import tests.helpers.factories.peri_scribe.areas
import tests.helpers.strategies.peri_scribe.areas


@hypothesis.given(
    mapping_entries=tests.helpers.strategies.peri_scribe.areas.history_entries(),
    report_entries=tests.helpers.strategies.peri_scribe.areas.history_entries(),
)
def test_area_history_never_uses_future_evidence(
    mapping_entries: list[tuple[float, float]],
    report_entries: list[tuple[float, float]],
) -> None:
    history = peri_scribe.areas.area_history(
        tests.helpers.factories.peri_scribe.areas.mappings(mapping_entries),
        tests.helpers.factories.peri_scribe.areas.reports(
            report_entries,
            confirmed=True,
        ),
    )
    assert all(item.observation_time <= item.time for item in history)


# This test is slow, so limit examples to keep routine test runs fast.
@hypothesis.settings(max_examples=25)
@hypothesis.given(
    mapping_entries=tests.helpers.strategies.peri_scribe.areas.history_entries(),
    report_entries=tests.helpers.strategies.peri_scribe.areas.history_entries(),
    data=hypothesis.strategies.data(),
)
def test_area_history_is_independent_of_input_row_order(
    mapping_entries: list[tuple[float, float]],
    report_entries: list[tuple[float, float]],
    data: hypothesis.strategies.DataObject,
) -> None:
    perimeters = tests.helpers.factories.peri_scribe.areas.mappings(mapping_entries)
    reports = tests.helpers.factories.peri_scribe.areas.reports(
        report_entries,
        confirmed=True,
    )
    mapping_order = data.draw(
        hypothesis.strategies.permutations(range(len(perimeters))),
    )
    report_order = data.draw(hypothesis.strategies.permutations(range(len(reports))))
    assert peri_scribe.areas.area_history(
        perimeters.iloc[list(mapping_order)],
        reports.iloc[list(report_order)],
    ) == peri_scribe.areas.area_history(perimeters, reports)


@hypothesis.given(entries=tests.helpers.strategies.peri_scribe.areas.history_entries())
def test_area_history_preserves_confirmed_reported_sizes(
    entries: list[tuple[float, float]],
) -> None:
    history = peri_scribe.areas.area_history(
        tests.helpers.factories.peri_scribe.areas.mappings([]),
        tests.helpers.factories.peri_scribe.areas.reports(entries, confirmed=True),
    )
    assert [item.area.m_as("acres") for item in history] == [
        area for _day, area in entries
    ]
