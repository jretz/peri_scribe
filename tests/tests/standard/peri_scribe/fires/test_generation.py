"""Authenticate source bytes without trusting disposable parsed caches or timestamps."""

from __future__ import annotations

import os
import pathlib

import pytest

import peri_scribe.execution
import peri_scribe.fires.generation
import peri_scribe.fires.reuse
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.snapshots


def test_source_key_shares_hashes_only_within_execution(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sources" / "feed" / "000001,lastEdit=1.gpkg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"snapshot")
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "derivation_context",
        lambda _year: "v1",
    )
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.generation.source_key(tmp_path)
        monkeypatch.setattr(
            peri_scribe.fires.reuse,
            "file_digest",
            lambda _path: "other",
        )
        assert peri_scribe.fires.generation.source_key(tmp_path) == first
    assert peri_scribe.fires.generation.source_key(tmp_path) != first


@pytest.mark.parametrize("change", ["bytes", "add", "delete", "rename", "order"])
def test_source_key_invalidates_authoritative_source_changes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    source = tmp_path / "sources" / "feed" / "000001,lastEdit=1.gpkg"
    other = source.with_name("000002,lastEdit=1.gpkg")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"first")
    other.write_bytes(b"second")
    stamp = source.stat()
    before = peri_scribe.fires.generation.source_key(tmp_path)
    if change == "bytes":
        source.write_bytes(b"other")
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == "add":
        source.with_name("000003,lastEdit=1.gpkg").write_bytes(b"new")
    elif change == "delete":
        source.unlink()
    elif change == "rename":
        source.rename(source.with_name("000001,lastEdit=2.gpkg"))
    else:
        monkeypatch.setattr(
            peri_scribe.sources.snapshots,
            "geo_package_files",
            lambda _directory: [other, source],
        )
    assert peri_scribe.fires.generation.source_key(tmp_path) != before


@pytest.mark.parametrize("change", ["boundary", "context"])
def test_source_key_invalidates_derivation_dependencies(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    before = peri_scribe.fires.generation.source_key(tmp_path)
    if change == "boundary":
        path = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
            tmp_path,
        )
        path.parent.mkdir(parents=True)
        path.write_bytes(b"boundary")
    else:
        monkeypatch.setattr(
            peri_scribe.fires.reuse,
            "derivation_context",
            lambda _year: "changed",
        )
    assert peri_scribe.fires.generation.source_key(tmp_path) != before


def test_source_key_ignores_disposable_caches_and_current_state(
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "sources" / "feed"
    directory.mkdir(parents=True)
    before = peri_scribe.fires.generation.source_key(tmp_path)
    for name in ("record_cache.db", "current.gpkg", "metadata.json"):
        (directory / name).write_bytes(b"disposable")
    assert peri_scribe.fires.generation.source_key(tmp_path) == before
