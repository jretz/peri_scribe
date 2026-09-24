"""Persistent preparation belongs to a year and an exact numerical environment."""

from __future__ import annotations

import pathlib
import sys
import types

import pyproj
import pytest
import shapely

import peri_scribe.execution
import peri_scribe.preparation
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.preparation


@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("owner", [None, False, True])
def test_unconditional_rebuild_inherits_owning_publication(
    tmp_path: pathlib.Path,
    *,
    requested: bool,
    owner: bool | None,
) -> None:
    if owner is None:
        assert (
            peri_scribe.preparation.unconditional_rebuild(requested=requested)
            is requested
        )
    else:
        with peri_scribe.preparation.scope(tmp_path, unconditional=owner):
            assert peri_scribe.preparation.unconditional_rebuild(
                requested=requested,
            ) is (requested or owner)


def test_runtime_fingerprint_changes_for_source_bytes_even_at_same_file_size(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "src" / "peri_scribe" / "preparation.py"
    path.parent.mkdir(parents=True)
    path.write_text("# first\n")
    monkeypatch.setattr(peri_scribe.preparation, "__file__", str(path))
    before = peri_scribe.preparation.runtime_fingerprint()
    path.write_text("# other\n")
    assert peri_scribe.preparation.runtime_fingerprint() != before


@pytest.mark.parametrize(
    ("module", "attribute"),
    [(sys, "version"), (shapely, "geos_version_string"), (pyproj, "proj_version_str")],
)
def test_runtime_fingerprint_invalidates_native_environment_changes(
    monkeypatch: pytest.MonkeyPatch,
    module: types.ModuleType,
    attribute: str,
) -> None:
    before = peri_scribe.preparation.runtime_fingerprint()
    monkeypatch.setattr(module, attribute, "a different native build")
    assert peri_scribe.preparation.runtime_fingerprint() != before


def test_scope_reuses_year_context_and_restores_outer_memory_scope(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.preparation, "runtime_fingerprint", lambda: "first")
    value = object()
    with peri_scribe.execution.sharing():
        peri_scribe.execution.put(peri_scribe.execution.Group.SOURCES, "input", value)
        with peri_scribe.preparation.scope(tmp_path):
            spatial_data.product_cache.put("test", "input", b"prepared")
            monkeypatch.setattr(
                peri_scribe.preparation,
                "runtime_fingerprint",
                lambda: "changed",
            )
            with peri_scribe.preparation.scope(tmp_path):
                assert spatial_data.product_cache.get("test", "input") == b"prepared"
            with peri_scribe.preparation.scope(tmp_path / "other"):
                assert spatial_data.product_cache.get("test", "input") is None
            assert spatial_data.product_cache.get("test", "input") == b"prepared"
        assert (
            peri_scribe.execution.get(
                peri_scribe.execution.Group.SOURCES,
                "input",
            )
            is value
        )
        assert not spatial_data.product_cache.active()
    assert not peri_scribe.execution.active()


def test_cached_year_preserves_arguments_and_refreshes_unconditional_results(
    tmp_path: pathlib.Path,
) -> None:
    stage = tests.helpers.doubles.peri_scribe.preparation.remembered_stage
    assert stage(tmp_path, b"one", b"two") == (tmp_path, False, None)
    assert stage(tmp_path, b"replacement") == (tmp_path, False, b"onetwo")
    assert stage(tmp_path, b"fresh", unconditional=True) == (tmp_path, True, None)
    assert stage(tmp_path) == (tmp_path, False, b"fresh")
    assert not peri_scribe.execution.active()
    assert not spatial_data.product_cache.active()


def test_scope_damaged_cache_does_not_prevent_computation(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "derived" / "prepared-products.sqlite"
    path.parent.mkdir()
    path.write_bytes(b"broken cache")
    with peri_scribe.preparation.scope(tmp_path):
        assert peri_scribe.execution.active()
        assert not spatial_data.product_cache.active()
    assert not peri_scribe.execution.active()
