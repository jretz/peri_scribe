from __future__ import annotations

import pathlib
import typing

import peri_scribe.fires.grouping
import peri_scribe.fires.proximity
import spatial_data.product_cache
import tests.formal.helpers.grouping
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.fires.grouping_cache


if typing.TYPE_CHECKING:
    import pytest


def test_group_fire_record_indices_matches_proved_union_components() -> None:
    cases = tests.formal.helpers.grouping.graph_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    for records, result in zip(cases, expected, strict=True):
        groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
        assert tests.formal.helpers.grouping.canonical(groups, len(records)) == result


def test_group_fire_record_indices_name_and_spatial_edges_match_lean() -> None:
    cases = tests.formal.helpers.grouping.spatial_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    for records, result in zip(cases, expected, strict=True):
        groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
        assert tests.formal.helpers.grouping.canonical(groups, len(records)) == result


def test_group_fire_record_indices_active_forest_matches_complete_lean_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.fires.proximity, "SMALL_QUERY_LIMIT", 0)
    cases = tests.formal.helpers.grouping.spatial_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    for records, result in zip(cases, expected, strict=True):
        groups = peri_scribe.fires.grouping.group_fire_record_indices(records)
        assert tests.formal.helpers.grouping.canonical(groups, len(records)) == result


def test_group_fire_record_indices_cached_blocks_match_complete_lean_graph(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.grouping.spatial_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [tests.formal.helpers.grouping.command(case) for case in cases],
        executable="oracleDomain",
    )
    with spatial_data.product_cache.scope(
        tmp_path / "products.sqlite",
        "formal grouping",
    ):
        for records, result in zip(cases, expected, strict=True):
            keys = tests.helpers.factories.peri_scribe.fires.grouping_cache.row_keys(
                records,
            )
            for _iteration in range(2):
                groups = peri_scribe.fires.grouping.group_fire_record_indices(
                    records,
                    row_keys=keys,
                )
                assert (
                    tests.formal.helpers.grouping.canonical(groups, len(records))
                    == result
                )
