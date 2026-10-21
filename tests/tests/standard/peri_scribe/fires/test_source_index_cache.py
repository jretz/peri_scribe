"""Retained dependency metadata survives interruption and rejects partial evidence."""

from __future__ import annotations

import dataclasses
import pathlib
import unittest.mock

import pydantic
import pytest
import shapely

import peri_scribe.fires.grouping_cache
import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.source_index_cache
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.geo.reading
import peri_scribe.geo.source_summaries
import peri_scribe.models
import peri_scribe.sources.feed_types
import peri_scribe.sources.snapshots
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.fires.source_index_cache
import tests.helpers.doubles.peri_scribe.sources.provenance
import tests.helpers.factories.peri_scribe.fires.source_index_cache
import tests.helpers.factories.peri_scribe.geo.package
import tests.helpers.factories.peri_scribe.models


def test_removed_bridge_invalidates_both_remaining_sides() -> None:
    row = peri_scribe.fires.source_index_cache.DependencyRow
    previous = peri_scribe.fires.source_index_cache.index_from_rows([
        row(path="a", position=0, evidence_key="one", identifiers=frozenset({"a"})),
        row(
            path="b",
            position=0,
            evidence_key="two",
            identifiers=frozenset({"a", "b"}),
        ),
        row(path="c", position=0, evidence_key="three", identifiers=frozenset({"b"})),
        row(path="d", position=0, evidence_key="four", names=frozenset({"a"})),
    ])
    current = peri_scribe.fires.source_index_cache.index_from_rows([
        previous.rows[0],
        previous.rows[2],
        previous.rows[3],
    ])
    assert peri_scribe.fires.source_index_cache.affected_rows(None, current) == {
        row.reference for row in current.rows
    }
    assert peri_scribe.fires.source_index_cache.changed_rows(previous, current) == {
        ("b", 0),
    }
    assert peri_scribe.fires.source_index_cache.affected_rows(previous, current) == {
        ("a", 0),
        ("c", 0),
    }


def test_reverse_index_rejects_duplicate_rows_and_missing_incidences() -> None:
    row = peri_scribe.fires.source_index_cache.DependencyRow(
        path="one",
        position=0,
        evidence_key="key",
        names=frozenset({"name"}),
    )
    with pytest.raises(pydantic.ValidationError, match="unique"):
        peri_scribe.fires.source_index_cache.index_from_rows([row, row])
    with pytest.raises(pydantic.ValidationError, match="exactly cover"):
        peri_scribe.fires.source_index_cache.DependencyIndex(rows=(row,), reverse=())


def test_dependency_index_constructs_reverse_once_but_cached_json_validates_again(
    tmp_path: pathlib.Path,
) -> None:
    _, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        contents,
    )
    with unittest.mock.patch.object(
        peri_scribe.fires.source_index_cache,
        "reverse_for",
        wraps=peri_scribe.fires.source_index_cache.reverse_for,
    ) as reverse:
        current = peri_scribe.fires.source_index_cache.dependency_index(read)
        assert reverse.call_count == 1
        reverse.reset_mock()
        restored = (
            peri_scribe.fires.source_index_cache.DependencyIndex.model_validate_json(
                current.model_dump_json(),
            )
        )
        assert reverse.call_count == 1
        assert restored == current


def test_dependency_index_rejects_duplicate_references_in_local_read(
    tmp_path: pathlib.Path,
) -> None:
    _, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        contents,
    )
    invalid = dataclasses.replace(read, positions=(0, 0, 0))
    with pytest.raises(pydantic.ValidationError, match="unique"):
        peri_scribe.fires.source_index_cache.dependency_index(invalid)


def test_dependency_index_validates_rows_before_internal_construction(
    tmp_path: pathlib.Path,
) -> None:
    _, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        contents,
    )
    invalid = dataclasses.replace(read, positions=(-1, 1, 0))
    with pytest.raises(pydantic.ValidationError, match="greater than or equal to 0"):
        peri_scribe.fires.source_index_cache.dependency_index(invalid)


def test_dependency_index_shares_exact_source_strings_with_provenance_and_output(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        contents,
    )
    calls = tests.helpers.doubles.peri_scribe.sources.provenance.RelativeCalls(
        original=pathlib.PurePath.relative_to,
    )
    monkeypatch.setattr(
        pathlib.PurePath,
        "relative_to",
        calls.method(),
    )
    current = peri_scribe.fires.source_index_cache.dependency_index(read)
    for row, path in zip(read.rows, read.paths, strict=True):
        peri_scribe.fires.reuse.provenance_key(
            row.row_key,
            path,
            tmp_path,
            source_paths=read.source_paths,
        )
    source = peri_scribe.models.FireSources(
        fire=prepared.groups.fires[0],
        paths=(read.paths[2], read.paths[0], read.paths[0]),
    )
    document = peri_scribe.fires.index.fire_sources_document(
        source,
        tmp_path,
        source_paths=read.source_paths,
    )
    assert document["paths"] == sorted([
        current.rows[2].path,
        current.rows[0].path,
        current.rows[0].path,
    ])
    assert len(calls.calls) == len(contents)


@pytest.mark.parametrize("payload", [b"bad", b"{}", b'{"rows":[],"reverse":[1]}'])
def test_corrupt_dependency_index_requires_complete_preparation(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.fires.source_index_cache.NAMESPACE,
            "current",
            payload,
        )
        assert (
            peri_scribe.fires.source_index_cache.prepare_index_sources(tmp_path) is None
        )


def test_hydration_rejects_changed_or_missing_rows(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "one.gpkg"
    row = peri_scribe.geo.package.FireRowRecord(
        record=tests.helpers.factories.peri_scribe.models.fire_record(
            "Canyon",
            peri_scribe.models.FireStatus.ACTIVE,
            geometry=shapely.Point(0, 0),
        ),
        object_id=None,
        source_name="test",
        attributes={},
    )
    original = peri_scribe.geo.package.GeopackageContents(rows=(row,), memberships=())
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        {path: original},
    )
    read.contents[path] = dataclasses.replace(original, rows=())
    with pytest.raises(ValueError, match="row count changed"):
        peri_scribe.fires.source_index_cache.hydrate_indices(read, [0])
    changed = dataclasses.replace(row, attributes={"new": "evidence"})
    read.contents[path] = dataclasses.replace(original, rows=(changed,))
    with pytest.raises(ValueError, match="evidence changed"):
        peri_scribe.fires.source_index_cache.hydrate_indices(read, [0])


def test_distinct_snapshots_with_equal_anchor_prefix_fall_back_to_complete_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [tmp_path / "first/one.gpkg", tmp_path / "second/one.gpkg"]
    row = peri_scribe.geo.package.FireRowRecord(
        record=tests.helpers.factories.peri_scribe.models.fire_record(
            "Canyon",
            peri_scribe.models.FireStatus.ACTIVE,
        ),
        object_id=1,
        source_name="test",
        attributes={},
    )
    contents = {
        path: peri_scribe.geo.package.GeopackageContents(rows=(row,), memberships=())
        for path in paths
    }
    read = tests.helpers.factories.peri_scribe.fires.source_index_cache.read(
        tmp_path,
        contents,
    )
    assert not peri_scribe.fires.source_index_cache.comparable_anchors(read)
    monkeypatch.setattr(
        peri_scribe.sources.snapshots,
        "geo_package_files",
        lambda _: paths,
    )
    summaries = {
        path: peri_scribe.geo.source_summaries.summarize(path, value)
        for path, value in contents.items()
    }
    monkeypatch.setattr(
        peri_scribe.geo.source_summaries,
        "read_summaries",
        lambda *_args, **_kwargs: (summaries, contents),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.fires.source_index_cache.NAMESPACE,
            "current",
            peri_scribe.fires.source_index_cache
            .dependency_index(read)
            .model_dump_json()
            .encode(),
        )
        assert (
            peri_scribe.fires.source_index_cache.prepare_index_sources(tmp_path) is None
        )


def test_interrupted_manifest_and_partition_update_retains_previous_commit(
    tmp_path: pathlib.Path,
    configured_feeds: list[peri_scribe.sources.feed_types.Feed],
) -> None:
    tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        configured_feeds[0],
        [("Canyon", "Active"), ("Canyon", "Active")],
    )
    directory = tmp_path / "sources"
    products = tmp_path / "products.sqlite"
    namespace = peri_scribe.fires.source_index_cache.NAMESPACE
    grouping_namespace = peri_scribe.fires.grouping_cache.NAMESPACE
    with spatial_data.product_cache.scope(products, "context"):
        read = peri_scribe.fires.sources.read_fire_sources(directory)
        prepared = peri_scribe.fires.sources.PreparedSources(
            read=read,
            groups=peri_scribe.fires.sources.group_fire_sources(read),
        )
        peri_scribe.fires.source_index_cache.remember_index_sources(directory, prepared)
        previous = spatial_data.product_cache.get(namespace, "current")
        before = peri_scribe.fires.source_index_cache.cached_index()
        assert before is not None
        old_key = peri_scribe.fires.grouping_cache.block_key(
            [row.evidence_key for row in before.rows],
            "0.05",
        )
        old_partition = spatial_data.product_cache.get(grouping_namespace, old_key)
        assert old_partition is not None
    tests.helpers.factories.peri_scribe.geo.package.write_cache_snapshot(
        tmp_path,
        configured_feeds[0],
        [("Canyon", "Inactive"), ("Canyon", "Active")],
    )
    abort = tests.helpers.doubles.peri_scribe.fires.source_index_cache.PreparationAbort(
        directory=directory,
        products=products,
    )
    with pytest.raises(RuntimeError, match="abort staged index"):
        abort()
    assert abort.manifests[0] != previous
    new_key, staged_partition = abort.partitions[0]
    assert staged_partition is not None
    with spatial_data.product_cache.scope(products, "context"):
        assert spatial_data.product_cache.get(namespace, "current") == previous
        assert (
            spatial_data.product_cache.get(grouping_namespace, old_key) == old_partition
        )
        assert spatial_data.product_cache.get(grouping_namespace, new_key) is None
        retried = peri_scribe.fires.source_index_cache.prepare_index_sources(directory)
        assert retried is not None
        complete = peri_scribe.fires.sources.group_fire_sources(
            peri_scribe.fires.sources.read_fire_sources(directory),
        )
        assert peri_scribe.fires.index.fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(retried.groups),
            directory,
        ) == peri_scribe.fires.index.fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(complete),
            directory,
        )


def test_unchanged_complex_metadata_reuses_partitions_and_hydrates_only_on_request(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        prepared, contents = (
            tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
                tmp_path,
            )
        )
        peri_scribe.fires.source_index_cache.remember_index_sources(tmp_path, prepared)
        reader = (
            tests.helpers.doubles.peri_scribe.fires.source_index_cache.SnapshotContents(
                contents=contents,
            )
        )
        monkeypatch.setattr(peri_scribe.geo.reading, "read_geopackages_cached", reader)
        plan = peri_scribe.fires.source_index_cache.prepare_index_sources(tmp_path)
        assert plan is not None
        assert not any(reader.calls)
        assert peri_scribe.fires.index.fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(plan.groups),
            tmp_path,
        ) == peri_scribe.fires.index.fire_index_entries(
            peri_scribe.fires.sources.fire_sources_from_groups(prepared.groups),
            tmp_path,
        )
        requested = (plan.groups.groups[0],)
        selected = plan.hydrate_groups(requested)
        assert selected.fires[0] is plan.groups.fires[0]
        assert len(selected.records) == len(requested[0])
        assert {path for call in reader.calls for path in call} == set(contents)


@pytest.mark.parametrize(
    "invalid",
    ["missing_file", "missing_checksum", "extra_path", "undated_membership"],
)
def test_summary_seeding_ignores_unattested_or_incomplete_caller_evidence(
    tmp_path: pathlib.Path,
    invalid: str,
) -> None:
    prepared, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    if invalid == "missing_file":
        next(iter(contents)).unlink()
    elif invalid == "missing_checksum":
        prepared = dataclasses.replace(
            prepared,
            read=dataclasses.replace(prepared.read, source_checksums=()),
        )
    elif invalid == "extra_path":
        prepared = dataclasses.replace(
            prepared,
            read=dataclasses.replace(
                prepared.read,
                paths=(tmp_path / "outside.gpkg",) * len(prepared.read.rows),
            ),
        )
    else:
        prepared = dataclasses.replace(
            prepared,
            read=dataclasses.replace(prepared.read, membership_paths=()),
        )
    peri_scribe.fires.source_index_cache.remember_index_sources(tmp_path, prepared)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        peri_scribe.fires.source_index_cache.remember_index_sources(tmp_path, prepared)
        assert peri_scribe.fires.source_index_cache.cached_index() is None


def test_summary_seeding_rejects_bytes_changed_after_complete_parse(
    tmp_path: pathlib.Path,
) -> None:
    prepared, contents = (
        tests.helpers.factories.peri_scribe.fires.source_index_cache.complex_sources(
            tmp_path,
        )
    )
    next(iter(contents)).write_bytes(b"changed after parse")
    with (
        spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"),
        pytest.raises(
            ValueError,
            match="changed before retaining",
        ),
    ):
        peri_scribe.fires.source_index_cache.remember_index_sources(tmp_path, prepared)
