"""Actual Merkle composition agrees with executable Lean tree and framing algebra."""

import pathlib

import peri_scribe.sources.manifest
import spatial_data.product_cache
import tests.formal.helpers.source_digest
import tests.formal.helpers.source_manifest


def test_manifest_utf8_fields_match_proved_zero_escaping() -> None:
    values = ("", "火🔥", "\x00", "a\x00b", "\x00\x01", "\x00\x00")
    expected = tests.formal.helpers.source_digest.encode([
        (value.encode(),) for value in values
    ])
    assert [peri_scribe.sources.manifest.framed(value) for value in values] == expected


def test_manifest_composition_and_reuse_match_actual_lean_root(
    tmp_path: pathlib.Path,
) -> None:
    cases = tests.formal.helpers.source_manifest.inventories()
    expected = tests.formal.helpers.source_manifest.roots(cases)
    assert [peri_scribe.sources.manifest.root(case) for case in cases] == expected
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "context"):
        for case, root in zip(cases, expected, strict=True):
            assert peri_scribe.sources.manifest.root(case) == root
            assert peri_scribe.sources.manifest.root(case) == root


def test_completed_root_input_keys_match_proved_ordered_pair_encoding() -> None:
    cases = tests.formal.helpers.source_manifest.inventories()
    assert [peri_scribe.sources.manifest.inventory_key(case) for case in cases] == (
        tests.formal.helpers.source_manifest.inventory_keys(cases)
    )
