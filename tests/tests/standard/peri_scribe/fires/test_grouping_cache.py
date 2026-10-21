"""Recompute complete affected closures while retaining exact occurrence partitions."""

from __future__ import annotations

import dataclasses
import pathlib
import unittest.mock

import pydantic
import pytest
import shapely

import peri_scribe.fires.connectivity
import peri_scribe.fires.grouping
import peri_scribe.fires.grouping_cache
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.fires.grouping
import tests.helpers.factories.peri_scribe.fires.grouping_cache
import tests.helpers.factories.peri_scribe.models


@pytest.mark.parametrize(
    ("groups", "count"),
    [
        (((1, 0),), 2),
        (((),), 0),
        (((1,), (0,)), 2),
        (((0, 0),), 2),
        (((-1,),), 1),
        (((0,), (2,)), 2),
        (((0,),), 2),
    ],
)
def test_partition_complete_rejects_invalid_occurrence_partitions(
    groups: tuple[tuple[int, ...], ...],
    count: int,
) -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fires.grouping_cache.Partition(count=count, groups=groups)


def test_partition_complete_accepts_empty_source() -> None:
    assert peri_scribe.fires.grouping_cache.Partition(count=0, groups=()).groups == ()


def test_dependency_blocks_preserves_all_possible_bridges() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"left"},
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Bridge",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"left", "right"},
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Canyon",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"right"},
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "Canyon",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.Point(100, 45),
        ),
    ]
    assert peri_scribe.fires.grouping_cache.dependency_blocks(records) == [[0, 1, 2, 3]]
    assert peri_scribe.fires.grouping_cache.dependency_blocks(
        [records[0], records[2], records[3]],
    ) == [[0], [1, 2]]


def test_grouped_indices_reuses_only_unchanged_dependency_blocks(
    tmp_path: pathlib.Path,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            name,
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.Point(longitude, 0),
        )
        for name, longitude in (
            ("River", 0),
            ("Canyon", 10),
            ("River", 0.04),
            ("Canyon", 10.04),
        )
    ]
    calculator = tests.helpers.doubles.peri_scribe.fires.grouping.PartitionCalculator()
    changed = list(records)
    changed[2] = dataclasses.replace(records[2], geometry=shapely.Point(2, 0))
    histories = (
        (records, [[0, 2], [1, 3]]),
        (records, [[0, 2], [1, 3]]),
        (changed, [[0], [1, 3], [2]]),
    )
    for current, expected in histories:
        with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
            result = peri_scribe.fires.grouping_cache.grouped_indices(
                current,
                tests.helpers.factories.peri_scribe.fires.grouping_cache.row_keys(
                    current,
                ),
                "policy",
                calculator.calculate,
            )
        assert result == expected
    assert [tuple(record.name for record in call) for call in calculator.calls] == [
        ("River", "River"),
        ("Canyon", "Canyon"),
        ("River", "River"),
    ]


@pytest.mark.parametrize("identifier_bridge", [False, True])
def test_grouped_indices_recomputes_after_bridge_removal(
    tmp_path: pathlib.Path,
    *,
    identifier_bridge: bool,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            str(index) if identifier_bridge else "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers=identifiers if identifier_bridge else (),
            geometry=shapely.Point(index * 0.04, 0),
        )
        for index, identifiers in enumerate(({"left"}, {"left", "right"}, {"right"}))
    ]
    for current, expected in (
        (records, [[0, 1, 2]]),
        ([records[0], records[2]], [[0], [1]]),
    ):
        with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
            assert (
                peri_scribe.fires.grouping.group_fire_record_indices(
                    current,
                    row_keys=tests.helpers.factories.peri_scribe.fires.grouping_cache.row_keys(
                        current,
                    ),
                )
                == expected
            )


@pytest.mark.parametrize("payload", [b"not json", b'{"count":3,"groups":[[0,1,2]]}'])
def test_cached_partition_rejects_invalid_or_incompatible_payload(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.fires.grouping_cache.NAMESPACE,
            "key",
            payload,
        )
        assert peri_scribe.fires.grouping_cache.cached_partition("key", 2) is None


def test_grouped_indices_validates_complete_row_key_alignment() -> None:
    with pytest.raises(ValueError, match="align"):
        peri_scribe.fires.grouping_cache.grouped_indices(
            [],
            ["extra"],
            "policy",
            peri_scribe.fires.grouping.group_fire_record_indices,
        )
    with pytest.raises(ValueError, match="align"):
        peri_scribe.fires.grouping.group_fire_record_indices([], row_keys=["extra"])


def test_group_fire_record_indices_can_use_row_keys_without_product_storage() -> None:
    assert peri_scribe.fires.grouping.group_fire_record_indices([], row_keys=[]) == []


def test_group_fire_record_indices_skips_identifier_connected_name_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            identifiers={"shared"},
            geometry=shapely.Point(index * 20, 0),
        )
        for index in range(3)
    ]
    observed = unittest.mock.Mock(
        wraps=peri_scribe.fires.grouping.named_representatives,
    )
    monkeypatch.setattr(peri_scribe.fires.grouping, "named_representatives", observed)
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == [[0, 1, 2]]
    observed.assert_not_called()


def test_merge_records_by_name_supports_a_union_without_exposed_roots() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.Point(longitude, 0),
        )
        for longitude in (0, 0.04)
    ]
    components = peri_scribe.fires.connectivity.UnionFind.for_count(len(records))
    peri_scribe.fires.grouping.merge_records_by_name(records, components.union)
    assert components.groups() == [[0, 1]]


@pytest.mark.parametrize("geometry", [None, shapely.Point()])
def test_group_fire_record_indices_requires_usable_geometry_for_name_only_edges(
    geometry: shapely.Geometry | None,
) -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.Point(0, 0),
        ),
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=geometry,
        ),
    ]
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == [[0], [1]]


def test_group_fire_record_indices_connects_one_exact_geometry_class() -> None:
    records = [
        tests.helpers.factories.peri_scribe.models.fire_record(
            "River",
            tests.helpers.factories.peri_scribe.models.ACTIVE,
            geometry=shapely.Point(0, 0),
        )
        for _index in range(2)
    ]
    assert peri_scribe.fires.grouping.group_fire_record_indices(records) == [[0, 1]]


def test_matched_within_outlier_tolerance_owns_keys_for_standalone_calls() -> None:
    assert peri_scribe.fires.grouping.matched_within_outlier_tolerance([
        (0, shapely.Point(0, 0)),
        (1, shapely.Point(0.5, 0)),
        (2, shapely.Point(10, 0)),
    ]) == {0, 1}
