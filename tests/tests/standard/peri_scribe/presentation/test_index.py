"""Tests for peri_scribe.presentation.builder."""

from __future__ import annotations

import peri_scribe.execution
import peri_scribe.presentation.index
import tests.helpers.factories.geography
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.time


def test_prepare_histories_shares_equal_index_inputs_within_one_run() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.index.prepare_histories(index, empty, empty)
        second = peri_scribe.presentation.index.prepare_histories(
            index.model_copy(deep=True),
            empty,
            empty,
        )
    assert first is second


def test_prepare_histories_rebuilds_between_runs() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.index.prepare_histories(index, empty, empty)
    with peri_scribe.execution.sharing():
        second = peri_scribe.presentation.index.prepare_histories(index, empty, empty)
    assert first is not second


def test_prepare_histories_rebuilds_for_replaced_sources() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.index.prepare_histories(index, empty, empty)
        second = peri_scribe.presentation.index.prepare_histories(
            index,
            empty.copy(),
            empty,
        )
    assert first is not second


def test_prepare_histories_rebuilds_when_alias_membership_changes() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier="example",
        ),
    ])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    incidents = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["alias"],
            "fire_name": ["Example"],
            "incident_size": [100],
        },
        [None],
    )
    with peri_scribe.execution.sharing():
        first = peri_scribe.presentation.index.prepare_histories(
            index,
            empty,
            empty,
            incidents,
        )
        index.fires[0].aliases.append("alias")
        second = peri_scribe.presentation.index.prepare_histories(
            index,
            empty,
            empty,
            incidents,
        )
    assert set(first) == {("id", "alias")}
    assert set(second) == {("id", "example")}


def test_area_qualified_index_includes_independent_incident_history() -> None:
    index = tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
            "Example",
            "active",
            identifier="example",
        ),
    ])
    empty = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    incidents = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": ["example"],
            "fire_name": ["Example"],
            "observation_time": [tests.helpers.factories.time.utc(2026, 9, 1, 0)],
            "incident_size": [100],
            "report_confirmed": [False],
        },
        [None],
    )
    assert (
        peri_scribe.presentation.index.area_qualified_index(
            index,
            empty,
            empty,
            incidents,
        )
        == index
    )
