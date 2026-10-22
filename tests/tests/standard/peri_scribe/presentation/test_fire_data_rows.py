"""Current shared columns preserve latest-row facts and exact evidence keys."""

import pathlib

import geopandas
import pytest

import peri_scribe.history_columns
import peri_scribe.presentation.fire_data
import spatial_data.frame_fingerprints
import spatial_data.product_cache
import tests.helpers.factories.peri_scribe.fires.scores


@pytest.mark.parametrize("positions", [(), (0,), (1,)])
def test_latest_row_fingerprints_agree_with_selected_source_frames(
    positions: tuple[int, ...],
) -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.reported_frame([
        ("example", "Example", 100),
        ("example", "Example", 200),
    ])
    columns = peri_scribe.history_columns.HistoryColumns.from_frame(frame)
    actual = peri_scribe.presentation.fire_data.latest_row_fingerprints(
        (columns.select(positions),),
        (spatial_data.frame_fingerprints.frame_schema(frame),),
    )
    assert actual == (
        spatial_data.frame_fingerprints.frame_rows(frame.iloc[list(positions)]),
    )


def test_latest_row_fingerprints_retain_frame_fallback() -> None:
    frame = geopandas.GeoDataFrame({"value": [1]})
    assert peri_scribe.presentation.fire_data.latest_row_fingerprints(
        (frame,),
        (spatial_data.frame_fingerprints.frame_schema(frame),),
    ) == (spatial_data.frame_fingerprints.frame_rows(frame),)


def test_latest_row_fingerprints_decline_unsupported_cache_scalars() -> None:
    frame = geopandas.GeoDataFrame({"value": [object()]})
    columns = peri_scribe.history_columns.HistoryColumns.from_frame(frame)
    assert (
        peri_scribe.presentation.fire_data.latest_row_fingerprints(
            (columns.select((0,)),),
            (spatial_data.frame_fingerprints.frame_schema(frame),),
        )
        is None
    )


def test_description_schemas_declines_unsupported_column_labels(
    tmp_path: pathlib.Path,
) -> None:
    frame = geopandas.GeoDataFrame({object(): [1]})
    with spatial_data.product_cache.scope(tmp_path / "cache.sqlite", "policy"):
        assert peri_scribe.presentation.fire_data.description_schemas((frame,)) == ()
