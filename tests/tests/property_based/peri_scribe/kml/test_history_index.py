"""Tests for peri_scribe.kml.history_index."""

from __future__ import annotations

import geopandas.testing
import hypothesis
import hypothesis.strategies

import peri_scribe.kml.history_index
import tests.helpers.factories.peri_scribe.kml.history_index
import tests.helpers.reference.peri_scribe.kml.history_index
import tests.helpers.strategies.peri_scribe.kml.history_index


@hypothesis.given(
    rows=tests.helpers.strategies.peri_scribe.kml.history_index.history_rows(),
    identifiers=hypothesis.strategies.frozensets(
        hypothesis.strategies.sampled_from(("0", "1", "", "River", "Cañon", "missing")),
    ),
    name=hypothesis.strategies.sampled_from(
        ("0", "1", "", "River", "Cañon", "missing"),
    ),
    labels=hypothesis.strategies.data(),
)
def test_history_row_index_positions_for_matches_dataframe_filtering(
    rows: list[tuple[object, object]],
    identifiers: frozenset[str],
    name: str,
    labels: hypothesis.strategies.DataObject,
) -> None:
    frame = tests.helpers.factories.peri_scribe.kml.history_index.history_frame(rows)
    frame.index = labels.draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(-5, 5),
            min_size=len(rows),
            max_size=len(rows),
        ),
    )
    index = peri_scribe.kml.history_index.HistoryRowIndex.from_frame(frame)
    actual = peri_scribe.kml.history_index.select_rows(
        frame,
        index.positions_for(identifiers, name),
    )
    expected = (
        tests.helpers.reference.peri_scribe.kml.history_index.reference_selection(
            frame,
            identifiers,
            name,
        )
    )
    geopandas.testing.assert_geodataframe_equal(actual, expected)
