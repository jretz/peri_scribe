"""Fresh boundary reuse preserves forced behavior and releases bounded storage."""

import io
import pathlib
import typing
from unittest.mock import patch

import pytest
import shapely

import kml_io.fragments
import kml_io.geometry
import spatial_data.cache_values
import spatial_data.product_cache
import tests.helpers.doubles.kml_io.fragments
import tests.helpers.factories.kml_io.geometry


def test_document_spill_reuses_forced_fragments_beyond_memory_budget(
    tmp_path: pathlib.Path,
) -> None:
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    writer.geometry_cache.budget = 1
    geometry = shapely.Polygon(
        [(-0.000001, 0), (2, 0), (2, 2), (0, 2)],
        holes=[[(0.5, 0.5), (1, 0.5), (1, 1), (0.5, 1)]],
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "policy"):
        spatial_data.product_cache.put(
            kml_io.fragments.NAMESPACE,
            kml_io.fragments.geometry_key(geometry, 5),
            spatial_data.cache_values.dumps(
                kml_io.geometry.geometry_boundaries(shapely.box(9, 9, 10, 10)),
            ),
        )
    with (
        spatial_data.product_cache.scope(
            tmp_path / "products.sqlite",
            "policy",
            unconditional=True,
        ),
        writer.document("Document", ()),
    ):
        first = writer.geometry_cache.boundaries(geometry, 5, renderer)
        second = writer.geometry_cache.boundaries(geometry, 5, renderer)
        spool = writer.geometry_cache.spool
        assert spool is not None
        stream = spool.stream
        assert not stream.closed
        assert spool.size <= spool.budget
        assert len(spool.entries) <= spool.limit
        assert first == second == kml_io.geometry.geometry_boundaries(geometry)
        assert "-0.00000" in first[0]
    assert stream.closed
    assert writer.geometry_cache.spool is None
    assert len(renderer.calls) == 1
    assert writer.geometry_cache.spill_hits == 1
    assert writer.geometry_cache.persistent_hits == 0
    assert writer.geometry_cache.retained_bytes == 0


def test_boundary_spill_does_not_reuse_previous_document() -> None:
    renderer = tests.helpers.doubles.kml_io.fragments.BoundaryRenderer()
    cache = kml_io.fragments.BoundaryCache(budget=1)
    geometry = shapely.box(0, 0, 1, 1)
    for _ in range(2):
        with cache.spill():
            cache.boundaries(geometry, 5, renderer)
    expected_calls = 2
    assert len(renderer.calls) == expected_calls
    assert cache.spill_hits == 0


def test_boundary_spill_closes_on_document_failure() -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    message = "document failed"
    with (
        io.BytesIO() as stream,
        patch("kml_io.fragments.tempfile.TemporaryFile", return_value=stream),
        pytest.raises(RuntimeError, match="document failed"),
        writer.document("Document", ()),
    ):
        raise RuntimeError(message)
    assert stream.closed
    assert writer.geometry_cache.spool is None


def test_boundary_spill_cleans_up_when_xml_opening_fails() -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    with (
        io.BytesIO() as stream,
        patch("kml_io.fragments.tempfile.TemporaryFile", return_value=stream),
        patch.object(
            writer,
            "write",
            side_effect=OSError("document write failed"),
        ),
        pytest.raises(OSError, match="document write failed"),
        writer.document("Document", ()),
    ):
        pytest.fail("The document must fail before yielding")
    assert stream.closed
    assert writer.geometry_cache.spool is None


def test_boundary_spill_open_failure_keeps_rendering_available() -> None:
    cache = kml_io.fragments.BoundaryCache(budget=1)
    with (
        patch("kml_io.fragments.tempfile.TemporaryFile", side_effect=OSError),
        cache.spill(),
    ):
        assert cache.spool is None
        assert cache.boundaries(
            shapely.box(0, 0, 1, 1),
            5,
            kml_io.geometry.geometry_boundaries,
        )


@pytest.mark.parametrize(("limit", "budget"), [(1, 4), (2, 2)])
def test_boundary_spool_caps_index_and_encoded_bytes(limit: int, budget: int) -> None:
    stream = io.BytesIO()
    spool = kml_io.fragments.BoundarySpool(stream, limit=limit, budget=budget)
    spool.put("first", b"a")
    spool.put("first", b"different")
    spool.put("second", b"b")
    spool.put("oversized", b"too large")
    assert spool.get("first") == b"a"
    assert spool.get("second") is None
    assert spool.get("oversized") is None
    assert len(stream.getvalue()) == spool.size <= budget
    assert len(spool.entries) <= limit


def test_boundary_spool_rejects_invalid_and_unauthenticated_frames() -> None:
    stream = io.BytesIO()
    spool = kml_io.fragments.BoundarySpool(stream)
    spool.put("key", b"a")
    stream.seek(0)
    stream.write(b"\x10b")
    assert spool.get("key") is None
    stream.seek(0)
    stream.write(b"\x00b")
    assert spool.get("key") is None


@pytest.mark.parametrize("short_write", [False, True])
def test_boundary_spool_failed_writes_never_publish_an_index(
    *,
    short_write: bool,
) -> None:
    stream = tests.helpers.doubles.kml_io.fragments.FailingStream(
        short_write=short_write,
    )
    spool = kml_io.fragments.BoundarySpool(typing.cast("typing.BinaryIO", stream))
    spool.put("first", b"a")
    spool.put("second", b"b")
    assert not spool.entries
    assert spool.disabled
    assert spool.size <= spool.budget


def test_boundary_spool_read_failure_is_a_miss() -> None:
    spool = kml_io.fragments.BoundarySpool(io.BytesIO())
    spool.put("key", b"a")
    spool.stream = typing.cast(
        "typing.BinaryIO",
        tests.helpers.doubles.kml_io.fragments.FailingStream(),
    )
    assert spool.get("key") is None


def test_boundary_spool_codec_limit_is_a_miss() -> None:
    spool = kml_io.fragments.BoundarySpool(io.BytesIO())
    with patch("spatial_data.payload_codec.encode", side_effect=ValueError):
        spool.put("key", b"a")
    assert spool.size == 0
    assert not spool.entries


def test_boundary_cache_rejects_malformed_fresh_spill() -> None:
    cache = kml_io.fragments.BoundaryCache(budget=1)
    geometry = shapely.box(0, 0, 1, 1)
    with cache.spill():
        assert cache.spool is not None
        cache.spool.put(
            kml_io.fragments.geometry_key(geometry, 5),
            spatial_data.cache_values.dumps(("<broken>",)),
        )
        assert cache.boundaries(geometry, 5, kml_io.geometry.geometry_boundaries) == (
            kml_io.geometry.geometry_boundaries(geometry)
        )
    assert cache.computed == 1
    assert cache.spill_hits == 0


def test_boundary_spool_roundtrips_compressed_frames() -> None:
    stream = io.BytesIO()
    spool = kml_io.fragments.BoundarySpool(stream)
    payload = b"-0.00000,1.12345 " * 1024
    spool.put("large", payload)
    assert spool.size < len(payload)
    assert spool.get("large") == payload


def test_boundary_spill_cleans_up_when_xml_closing_fails() -> None:
    writer = tests.helpers.factories.kml_io.geometry.MemoryKmlWriter()
    with (
        io.BytesIO() as stream,
        patch("kml_io.fragments.tempfile.TemporaryFile", return_value=stream),
        patch.object(
            writer,
            "write",
            side_effect=[None, None, OSError("close failed")],
        ),
        pytest.raises(OSError, match="close failed"),
        writer.document("Document", ()),
    ):
        pass
    assert stream.closed
    assert writer.geometry_cache.spool is None
