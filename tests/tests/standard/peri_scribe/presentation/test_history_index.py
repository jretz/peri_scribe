"""Tests for peri_scribe.presentation.history_index."""

from __future__ import annotations

import pandas as pd

import peri_scribe.presentation.history_index
import tests.helpers.assertions.peri_scribe.presentation.history_index
import tests.helpers.factories.peri_scribe.presentation.history_index
import tests.helpers.reference.peri_scribe.presentation.history_index


def test_from_frame_indexes_rows_by_identifier_and_name() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
            (None, "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert dict(index.positions_by_identifier) == {"id-bug": (0, 2), "id-alta": (1,)}
    # The identifier-bearing rows are also reachable by name.
    assert dict(index.positions_by_name) == {"Bug": (0, 2, 3), "ALTA": (1,)}


def test_positions_for_matches_identifier_only() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
            (None, "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_for(frozenset({"id-bug"}), "Bug") == (0, 2)


def test_positions_for_never_falls_back_to_name_for_identifier_fire() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            (None, "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    # The identifier-less row shares the name but must not be matched.
    assert index.positions_for(frozenset({"id-bug"}), "Bug") == (0,)


def test_positions_for_falls_back_to_name_including_identifier_rows() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    # A fire without identifiers matches every row sharing its name, even the rows that
    # carry an identifier.
    assert index.positions_for(frozenset(), "Bug") == (0, 2)
    assert index.positions_for(frozenset(), "ALTA") == (1,)


def test_positions_for_returns_empty_for_unknown_fire() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_for(frozenset({"id-other"}), "Bug") == ()
    assert index.positions_for(frozenset(), "Other") == ()


def test_positions_for_merges_aliases_in_chronological_order() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alias", "Bug"),
            ("id-bug", "Bug"),
            ("id-other", "Other"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_for(frozenset({"id-bug", "id-alias"}), "Bug") == (0, 1, 2)


def test_missing_identifiers_are_indexed_by_name_only() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            (None, "Bug"),
            (float("nan"), "Bug"),
            (pd.NA, "Bug"),
            ("id-bug", "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_by_identifier == {"id-bug": (3,)}
    assert index.positions_by_name == {"Bug": (0, 1, 2, 3)}


def test_non_string_identifier_never_matches_string_fire_identifier() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            (1, "Bug"),
            ("1", "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    # The int identifier and the str identifier are distinct, mirroring ``isin``.
    assert index.positions_for(frozenset({"1"}), "Bug") == (1,)


def test_missing_name_is_never_matched_by_name() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-lost", None),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_by_identifier == {"id-bug": (0,), "id-lost": (1,)}
    assert index.positions_by_name == {"Bug": (0,)}
    assert index.positions_for(frozenset(), "None") == ()


def test_dual_membership_stores_identifier_rows_twice() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            (None, "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    stored = sum(
        len(positions) for positions in index.positions_by_identifier.values()
    ) + sum(len(positions) for positions in index.positions_by_name.values())
    # Three rows, plus one extra listing for each of the two identifier rows.
    assert stored == len(frame) + 2


def test_select_rows_returns_the_requested_rows_in_order() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
        ])
    )
    selected = peri_scribe.presentation.history_index.select_rows(frame, (2, 0))
    assert list(selected["fire_identifier"]) == ["id-bug", "id-bug"]
    assert selected.geometry.iloc[0].equals(frame.geometry.iloc[2])
    assert selected.geometry.iloc[1].equals(frame.geometry.iloc[0])


def test_select_rows_returns_empty_frame_for_no_positions() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
        ])
    )
    selected = peri_scribe.presentation.history_index.select_rows(frame, ())
    assert selected.empty
    assert list(selected.columns) == list(frame.columns)


def test_from_frame_handles_an_empty_frame() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    assert index.positions_by_identifier == {}
    assert index.positions_by_name == {}
    assert index.positions_for(frozenset({"id-bug"}), "Bug") == ()


def test_positions_for_matches_reference_filters() -> None:
    frames = [
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
            ("id-bug", "Bug"),
            (None, "Bug"),
            (None, "Other"),
        ]),
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            (None, "Bug"),
            (float("nan"), "Bug"),
            ("id-a", "Bug"),
            ("id-b", "ALTA"),
        ]),
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-a", "Bug"),
            (None, "Bug"),
            ("id-b", "Bug"),
            ("id-a", "ALTA"),
        ]),
    ]
    probes = [
        (frozenset({"id-bug"}), "Bug"),
        (frozenset({"id-alta"}), "ALTA"),
        (frozenset({"id-a"}), "Bug"),
        (frozenset({"id-a", "id-b"}), "Bug"),
        (frozenset(), "Bug"),
        (frozenset(), "ALTA"),
        (frozenset(), "Missing"),
        (frozenset({"id-missing"}), "Bug"),
    ]
    for frame in frames:
        index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
        for fire_identifiers, name in probes:
            expected = (
                tests.helpers.reference.peri_scribe.presentation.history_index
            ).select(
                frame,
                fire_identifiers,
                name,
            )
            actual = peri_scribe.presentation.history_index.select_rows(
                frame,
                index.positions_for(fire_identifiers, name),
            )
            tests.helpers.assertions.peri_scribe.presentation.history_index.assert_same_rows(
                actual,
                expected,
            )


def test_selected_rows_preserve_chronological_order() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.history_index.history_frame([
            ("id-bug", "Bug"),
            ("id-alta", "ALTA"),
            ("id-bug", "Bug"),
            ("id-bug", "Bug"),
        ])
    )
    index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    positions = index.positions_for(frozenset({"id-bug"}), "Bug")
    assert positions == tuple(sorted(positions))
    assert positions == (0, 2, 3)
