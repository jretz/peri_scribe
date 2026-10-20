"""Column views preserve evidence while avoiding per-fire pandas row allocation."""

import datetime
import typing

import pandas as pd
import pytest
import shapely

import peri_scribe.history_columns
import tests.helpers.factories.peri_scribe.history_columns


@pytest.mark.parametrize("columnar", [False, True])
def test_rows_preserve_selected_order_and_field_presence(*, columnar: bool) -> None:
    frame = pd.DataFrame(
        {
            "name": ["first", "second", "third"],
            "measurement": pd.array([0, None, 2**60 + 1], dtype="Int64"),
        },
        index=[8, 8, 3],
    )
    if columnar:
        source = peri_scribe.history_columns.HistoryColumns.from_frame(frame).select(
            (2, 0, 2, 1),
        )
    else:
        source = frame.iloc[[2, 0, 2, 1]]
    rows = list(peri_scribe.history_columns.rows(source))
    assert [row.get("name") for row in rows] == ["third", "first", "third", "second"]
    assert [row.get("measurement") for row in rows[:3]] == [2**60 + 1, 0, 2**60 + 1]
    assert pd.isna(rows[3].get("measurement"))
    assert peri_scribe.history_columns.has_field(rows[0], "name")
    assert not peri_scribe.history_columns.has_field(rows[0], "absent")
    assert rows[0].get("absent", "fallback") == "fallback"
    assert peri_scribe.history_columns.last_row(source).get("name") == "second"
    assert [
        row.get("name")
        for row in peri_scribe.history_columns.rows(
            source,
            reverse=True,
        )
    ] == ["second", "third", "first", "third"]


def test_history_columns_from_frame_retains_missing_values_and_borrows_geometry() -> (
    None
):
    geometry = shapely.Point(-120, 40)
    attributes = {"ModifiedBySystem": "ics209"}
    time = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    frame = pd.DataFrame({
        "geometry": [geometry, None],
        "source_attributes": [attributes, None],
        "observation_time": [time, pd.NaT],
        "nullable": pd.array([1, None], dtype="Int64"),
        "floating": [0.0, float("nan")],
    })
    columns = peri_scribe.history_columns.HistoryColumns.from_frame(frame)
    selected = columns.select((1, 0))
    rows = list(peri_scribe.history_columns.rows(selected))
    assert not selected.empty
    assert rows[1].get("geometry") is geometry
    assert rows[1].get("source_attributes") is attributes
    assert rows[1].get("observation_time") == time
    assert rows[0].get("observation_time") is pd.NaT
    assert rows[0].get("nullable") is pd.NA
    assert pd.isna(rows[0].get("floating"))
    assert rows[0].get("geometry", "fallback") is None
    assert selected.get("geometry") == (None, geometry)
    assert selected.get("absent") == ()
    assert selected.get("absent", (1,)) == (1,)
    assert columns.select(()).empty
    assert columns.select(()).get("geometry") == ()
    frame.loc[0, "geometry"] = None
    assert rows[1].get("geometry") is geometry
    with pytest.raises(TypeError):
        typing.cast("dict[str, tuple[object, ...]]", columns.fields)["geometry"] = ()


@pytest.mark.parametrize("columnar", [False, True])
@pytest.mark.parametrize("row_count", [0, 2])
def test_history_rows_empty_matches_dataframe_axes(
    *,
    columnar: bool,
    row_count: int,
) -> None:
    source = tests.helpers.factories.peri_scribe.history_columns.representation(
        pd.DataFrame(index=range(row_count)),
        columnar=columnar,
    )
    assert source.empty
    assert len(list(peri_scribe.history_columns.rows(source))) == row_count


@pytest.mark.parametrize("columns", [["same", "same"], ["name", 0]])
def test_history_columns_from_frame_rejects_ambiguous_or_nonstring_fields(
    columns: list[object],
) -> None:
    with pytest.raises(ValueError, match="unique string names"):
        peri_scribe.history_columns.HistoryColumns.from_frame(
            pd.DataFrame(
                [["first", "second"]],
                columns=columns,
            ),
        )
