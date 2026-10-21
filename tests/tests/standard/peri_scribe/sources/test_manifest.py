"""Ordered Merkle manifests preserve every source occurrence and source field."""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

import peri_scribe.sources.manifest
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.sources.manifest
import tests.helpers.reference.peri_scribe.sources.manifest


@pytest.mark.parametrize(
    "changed",
    [
        [("a", "other"), ("b", "two"), ("c", "three")],
        [("renamed", "one"), ("b", "two"), ("c", "three")],
        [("b", "two"), ("a", "one"), ("c", "three")],
        [("a", "one"), ("b", "two")],
        [("a", "one"), ("b", "two"), ("c", "three"), ("c", "three")],
    ],
)
def test_root_preserves_source_content_paths_order_and_multiplicity(
    changed: list[tuple[str, str]],
) -> None:
    original = [("a", "one"), ("b", "two"), ("c", "three")]
    assert peri_scribe.sources.manifest.root(original) != (
        peri_scribe.sources.manifest.root(changed)
    )


def test_leaf_frames_both_fields_without_separator_ambiguity() -> None:
    assert peri_scribe.sources.manifest.leaf("ab", "c") != (
        peri_scribe.sources.manifest.leaf("a", "bc")
    )
    assert peri_scribe.sources.manifest.framed("火") == "火".encode() + b"\x00\x00"
    assert peri_scribe.sources.manifest.framed("火\x00🔥") == (
        "火".encode() + b"\x00\x01" + "🔥".encode() + b"\x00\x00"
    )
    assert peri_scribe.sources.manifest.leaf("a\x00", "b") != (
        peri_scribe.sources.manifest.leaf("a", "\x00b")
    )


@pytest.mark.parametrize("size", range(41))
def test_iterative_root_matches_independent_recursive_tree(size: int) -> None:
    items = [(f"火/{index % 7}\x00", f"🔥{index % 5}") for index in range(size)]
    assert peri_scribe.sources.manifest.root(iter(items)) == (
        tests.helpers.reference.peri_scribe.sources.manifest.root(items).hex()
    )


def test_root_distinguishes_empty_single_and_duplicate_inventories() -> None:
    values = [[], [("a", "one")], [("a", "one"), ("a", "one")]]
    assert len({peri_scribe.sources.manifest.root(value) for value in values}) == len(
        values,
    )


def test_root_reuses_completed_branches_with_identical_children(
    tmp_path: pathlib.Path,
) -> None:
    items = [("a", "one"), ("b", "two"), ("c", "three")]
    without_storage = peri_scribe.sources.manifest.root(items)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        first = peri_scribe.sources.manifest.root(items)
        branches = peri_scribe.sources.manifest.cached_branches()
        second = peri_scribe.sources.manifest.root(items)
        assert len(branches) == len(items) - 1
        assert peri_scribe.sources.manifest.cached_branches() == branches
        assert first == second == without_storage
        for (left, right), parent in branches.items():
            assert (
                parent
                == hashlib.sha256(
                    b"\x01" + bytes.fromhex(left) + bytes.fromhex(right),
                ).hexdigest()
            )
        changed = [*items[:-1], ("c", "changed")]
        assert peri_scribe.sources.manifest.root(changed) == (
            tests.helpers.reference.peri_scribe.sources.manifest.root(changed).hex()
        )
        assert (
            len(branches.keys() & peri_scribe.sources.manifest.cached_branches().keys())
            == 1
        )


def test_completed_root_receipt_skips_branch_reads_for_exact_generator_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [("a", "one"), ("火\x00", "two"), ("c", "three")]
    expected = tests.helpers.reference.peri_scribe.sources.manifest.root(items).hex()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        assert peri_scribe.sources.manifest.root(iter(items)) == expected
        monkeypatch.setattr(
            peri_scribe.sources.manifest,
            "cached_branches",
            tests.helpers.doubles.peri_scribe.sources.manifest.reject_branch_read,
        )
        assert peri_scribe.sources.manifest.root(iter(items)) == expected


@pytest.mark.parametrize(
    "payload",
    [b"", b"a" * 63, b"g" * 64, b"A" * 64, b"\xff" * 64, "火" * 64],
)
def test_malformed_complete_root_receipts_recompute_exact_inventory(
    tmp_path: pathlib.Path,
    payload: bytes | str,
) -> None:
    items = [("a", "one"), ("b", "two")]
    key = peri_scribe.sources.manifest.inventory_key(items)
    expected = tests.helpers.reference.peri_scribe.sources.manifest.root(items).hex()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.sources.manifest.ROOT_NAMESPACE,
            key,
            payload.encode() if isinstance(payload, str) else payload,
        )
        assert peri_scribe.sources.manifest.cached_root(key) is None
        assert peri_scribe.sources.manifest.root(items) == expected
        assert peri_scribe.sources.manifest.cached_root(key) == expected


def test_completed_root_receipts_retain_only_current_ordered_inventory(
    tmp_path: pathlib.Path,
) -> None:
    first = [("a", "one"), ("b", "two")]
    second = list(reversed(first))
    first_key = peri_scribe.sources.manifest.inventory_key(first)
    second_key = peri_scribe.sources.manifest.inventory_key(second)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        first_root = peri_scribe.sources.manifest.root(first)
        assert peri_scribe.sources.manifest.cached_root(first_key) == first_root
        second_root = peri_scribe.sources.manifest.root(second)
        assert first_root != second_root
        assert peri_scribe.sources.manifest.cached_root(first_key) is None
        assert peri_scribe.sources.manifest.cached_root(second_key) == second_root


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        b"{}",
        b"[1]",
        b"[[]]",
        b"[[1,2,3]]",
        b'[["a","b","c"]]',
        json.dumps([["a" * 64, "b" * 64, "z" * 64]]).encode(),
    ],
)
def test_cached_branches_rejects_malformed_payloads(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.sources.manifest.NAMESPACE,
            "current",
            payload,
        )
        assert peri_scribe.sources.manifest.cached_branches() == {}


def test_cached_branches_rejects_duplicate_child_receipts(
    tmp_path: pathlib.Path,
) -> None:
    entry = ["a" * 64, "b" * 64, "c" * 64]
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        spatial_data.product_cache.put(
            peri_scribe.sources.manifest.NAMESPACE,
            "current",
            json.dumps([entry, entry]).encode(),
        )
        assert peri_scribe.sources.manifest.cached_branches() == {}
