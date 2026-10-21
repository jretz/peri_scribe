"""Source summaries select current authenticated projections and hydrate only misses."""

import dataclasses
import hashlib
import json
import pathlib
import unittest.mock

import pytest

import peri_scribe.fires.complexes
import peri_scribe.fires.components
import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.geo.reading
import peri_scribe.geo.source_summaries
import spatial_data.geometry_pool
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.geo.source_summaries
import tests.helpers.factories.peri_scribe.geo.database
import tests.helpers.factories.peri_scribe.geo.source_summaries


def test_summarize_preserves_anchor_order_and_singleton_identities() -> None:
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    row = contents.rows[0]
    rows = (
        dataclasses.replace(row, object_id=None, attributes={"revision": 2}),
        dataclasses.replace(row, object_id=None, attributes={"revision": 1}),
        row,
        row,
    )
    snapshot = dataclasses.replace(contents, rows=rows)
    path = pathlib.Path("feed/000___/000001,lastEdit=1.gpkg")
    summary = peri_scribe.geo.source_summaries.summarize(path, snapshot)
    anchors = peri_scribe.fires.components.anchors(rows, (path,) * len(rows))
    expected_order = sorted(range(len(rows)), key=anchors.__getitem__)
    assert (
        sorted(
            range(len(rows)),
            key=lambda position: summary.rows[position].anchor_order,
        )
        == expected_order
    )
    assert [row.anchor_digest for row in summary.rows] == [
        peri_scribe.fires.components.component_id([anchor]) for anchor in anchors
    ]
    assert [row.row_key for row in summary.rows] == [
        peri_scribe.geo.fingerprints.complete_row_fingerprint(row) for row in rows
    ]
    assert all(row.record.geometry is None for row in summary.rows)
    assert all(row.has_geometry for row in summary.rows)


def test_summarize_preserves_complete_dated_ownership_observations() -> None:
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    row = dataclasses.replace(
        contents.rows[0],
        attributes={
            "IsCpxChild": 1,
            "CpxID": "parent",
            "CpxName": "Parent Complex",
            "ModifiedOnDateTime_dt": "2026-06-01T00:00:00Z",
        },
    )
    contents = dataclasses.replace(contents, rows=(row,))
    path = pathlib.Path("WFIGS_Incident_Locations/000___/000001,lastEdit=1.gpkg")
    summary = peri_scribe.geo.source_summaries.summarize(path, contents)
    assert summary.memberships == contents.memberships
    assert summary.observations == tuple(
        peri_scribe.fires.complexes.observations(
            contents.rows,
            (path,),
            contents.memberships,
            (path,) * len(contents.memberships),
        ),
    )
    assert any(item.complex_identifier == "parent" for item in summary.observations)
    assert summary.row_observation_count == 1


def test_seed_summaries_round_trips_complete_projection(tmp_path: pathlib.Path) -> None:
    directory = tmp_path / "sources"
    path = tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
        directory,
        1,
        1,
    )
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    expected = peri_scribe.geo.source_summaries.summarize(path, contents)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        peri_scribe.geo.source_summaries.seed_summaries(
            directory,
            {path: contents},
            {path: peri_scribe.geo.database.snapshot_checksum(path)},
        )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        assert (
            peri_scribe.geo.source_summaries.read_snapshot_summary(
                path,
                directory,
                peri_scribe.geo.database.snapshot_checksum(path),
            )
            == expected
        )


def test_read_summaries_hydrates_only_changed_snapshot(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "sources"
    paths = [
        tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
            directory,
            serial,
            1,
        )
        for serial in (1, 2)
    ]
    original = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    changed = tests.helpers.factories.peri_scribe.geo.database.contents(2)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        peri_scribe.geo.source_summaries.seed_summaries(
            directory,
            dict.fromkeys(paths, original),
            {path: peri_scribe.geo.database.snapshot_checksum(path) for path in paths},
        )
    paths[1].write_bytes(b"2")
    read = unittest.mock.Mock(return_value={paths[1]: changed})
    monkeypatch.setattr(peri_scribe.geo.reading, "read_geopackages_cached", read)
    pool = spatial_data.geometry_pool.GeometryPool()
    fallback = unittest.mock.Mock()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        summaries, hydrated = peri_scribe.geo.source_summaries.read_summaries(
            paths,
            directory,
            geometry_pool=pool,
            read_fallback=fallback,
        )
    read.assert_called_once_with(
        [paths[1]],
        geometry_pool=pool,
        read_fallback=fallback,
    )
    assert hydrated == {paths[1]: changed}
    assert list(summaries) == paths
    assert summaries == {
        path: peri_scribe.geo.source_summaries.summarize(path, contents)
        for path, contents in zip(paths, (original, changed), strict=True)
    }


@pytest.mark.parametrize(
    "damage",
    ["payload", "shape", "path", "checksum", "context", "boundary"],
)
def test_read_snapshot_summary_rejects_unusable_products(
    tmp_path: pathlib.Path,
    damage: str,
) -> None:
    directory = tmp_path / "sources"
    path = tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
        directory,
        1,
        1,
    )
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    checksum = peri_scribe.geo.database.snapshot_checksum(path)
    namespace = peri_scribe.geo.source_summaries.NAMESPACE
    key = peri_scribe.geo.source_summaries.snapshot_key(path, directory, checksum)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        peri_scribe.geo.source_summaries.seed_summaries(
            directory,
            {path: contents},
            {path: checksum},
        )
        payload = spatial_data.product_cache.get(namespace, key)
        assert payload is not None
        if damage == "payload":
            store = spatial_data.product_cache.CURRENT.get()
            assert store is not None
            store.connection.execute(
                "UPDATE products SET value = ?",
                (b"damaged",),
            )
        else:
            document = json.loads(payload)
            if damage == "shape":
                document["rows"][0]["record"]["geometry"] = "unexpected payload"
            elif damage == "path":
                document["path"] = "different.gpkg"
            elif damage == "checksum":
                document["checksum"] = hashlib.sha256(b"different").hexdigest()
            elif damage == "boundary":
                document["row_observation_count"] = len(document["observations"]) + 1
            spatial_data.product_cache.put(
                namespace,
                key,
                json.dumps(document).encode(),
            )
    with spatial_data.product_cache.scope(
        tmp_path / "products.sqlite",
        "changed" if damage == "context" else "context",
    ):
        assert (
            peri_scribe.geo.source_summaries.read_snapshot_summary(
                path,
                directory,
                checksum,
            )
            is None
        )


def test_summarize_handles_empty_snapshot_and_missing_geometry() -> None:
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    path = pathlib.Path("manual-source.gpkg")
    row = dataclasses.replace(
        contents.rows[0],
        record=dataclasses.replace(contents.rows[0].record, geometry=None),
    )
    summary = peri_scribe.geo.source_summaries.summarize(
        path,
        dataclasses.replace(contents, rows=(row,)),
    )
    assert not summary.rows[0].has_geometry
    assert summary.rows[0].anchor_order[1] == -1
    assert not peri_scribe.geo.source_summaries.summarize(
        path,
        dataclasses.replace(contents, rows=()),
    ).rows


def test_seed_summaries_rejects_source_edit_after_complete_parse(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "sources"
    path = tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
        directory,
        1,
        1,
    )
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    checksum = peri_scribe.geo.database.snapshot_checksum(path)
    path.write_bytes(b"changed before seed")
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        with pytest.raises(OSError, match="Source changed during preparation"):
            peri_scribe.geo.source_summaries.seed_summaries(
                directory,
                {path: contents},
                {path: checksum},
            )
        assert (
            peri_scribe.geo.source_summaries.read_snapshot_summary(
                path,
                directory,
                peri_scribe.geo.database.snapshot_checksum(path),
            )
            is None
        )


def test_seed_summaries_rejects_incomplete_parse_identities(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "source.gpkg"
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    with pytest.raises(ValueError, match="authenticated paths must agree"):
        peri_scribe.geo.source_summaries.seed_summaries(
            tmp_path,
            {path: contents},
            {},
        )


def test_read_summaries_rejects_source_edit_while_hydrating(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "sources"
    path = tests.helpers.factories.peri_scribe.geo.source_summaries.snapshot(
        directory,
        1,
        1,
    )
    contents = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    monkeypatch.setattr(
        peri_scribe.geo.reading,
        "read_geopackages_cached",
        tests.helpers.doubles.peri_scribe.geo.source_summaries.ReadThenEdit(
            contents={path: contents},
        ),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        with pytest.raises(OSError, match="Source changed during preparation"):
            peri_scribe.geo.source_summaries.read_summaries(
                [path],
                directory,
                geometry_pool=spatial_data.geometry_pool.GeometryPool(),
            )
        assert (
            peri_scribe.geo.source_summaries.read_snapshot_summary(
                path,
                directory,
                peri_scribe.geo.database.snapshot_checksum(path),
            )
            is None
        )
