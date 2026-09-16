"""Tests for peri_scribe.sources.external_sources."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies
import shapely.geometry

import peri_scribe.sources.digests
import tests.helpers.factories.geography


@hypothesis.given(
    entries=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(0, 10),
            hypothesis.strategies.text(),
        ),
        min_size=1,
        max_size=15,
    ),
    data=hypothesis.strategies.data(),
)
def test_dataframe_digest_ignores_generated_row_and_column_order(
    entries: list[tuple[int, str]],
    data: hypothesis.strategies.DataObject,
) -> None:
    frame = tests.helpers.factories.geography.geo_frame(
        {
            "OBJECTID": [identifier for identifier, _value in entries],
            "value": [value for _identifier, value in entries],
        },
        [shapely.geometry.Point(identifier, 0) for identifier, _value in entries],
    )
    order = data.draw(hypothesis.strategies.permutations(range(len(entries))))
    reordered = frame.iloc[list(order)][list(reversed(frame.columns))]
    assert peri_scribe.sources.digests.dataframe_digest(
        reordered,
    ) == peri_scribe.sources.digests.dataframe_digest(frame)
