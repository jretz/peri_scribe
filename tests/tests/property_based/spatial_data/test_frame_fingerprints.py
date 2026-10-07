"""Positional subsets must have identical keys before and after materialization."""

import geopandas
import hypothesis
import hypothesis.strategies
import pandas as pd

import spatial_data.frame_fingerprints


@hypothesis.given(
    rows=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(),
            hypothesis.strategies.floats(),
            hypothesis.strategies.text(),
        ),
        min_size=1,
        max_size=20,
    ),
    data=hypothesis.strategies.data(),
)
def test_selected_key_matches_materialized_subsets(
    rows: list[tuple[int, float, str]],
    data: hypothesis.strategies.DataObject,
) -> None:
    frame = geopandas.GeoDataFrame(
        pd.DataFrame(rows, columns=["value", "value", "label"], dtype=object),
    )
    positions = data.draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.integers(0, len(rows) - 1),
            max_size=20,
        ),
    )
    original = spatial_data.frame_fingerprints.frame_rows(frame)
    selected = spatial_data.frame_fingerprints.frame_rows(
        geopandas.GeoDataFrame(frame.iloc[positions]),
    )
    assert spatial_data.frame_fingerprints.selected_key(
        (original,),
        (tuple(positions),),
        "example",
    ) == spatial_data.frame_fingerprints.selected_key(
        (selected,),
        (tuple(range(len(positions))),),
        "example",
    )
