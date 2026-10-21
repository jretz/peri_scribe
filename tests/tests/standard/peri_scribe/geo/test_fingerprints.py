"""Reusable row identities still observe exact typed and nested source changes."""

import contextlib
import copy
import dataclasses
import pathlib
import sqlite3
import struct
import unittest.mock

import pytest

import peri_scribe.geo.database
import peri_scribe.geo.fingerprints
import peri_scribe.geo.reading
import peri_scribe.models
import peri_scribe.sources.snapshots
import spatial_data.geometry_pool
import tests.helpers.doubles.peri_scribe.geo.fingerprints
import tests.helpers.factories.peri_scribe.geo.database


def test_row_evidence_fingerprint_recomputes_unattested_rows() -> None:
    row = tests.helpers.factories.peri_scribe.geo.database.contents(1).rows[0]
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(row) == (
        peri_scribe.geo.fingerprints.complete_row_fingerprint(row)
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [(True, 1), (1, 1.0), (0.0, -0.0), (None, "None"), ([1], (1,))],
)
def test_row_evidence_fingerprint_detects_typed_nested_attribute_changes(
    before: object,
    after: object,
) -> None:
    original = tests.helpers.factories.peri_scribe.geo.database.contents(1)
    row = dataclasses.replace(
        original.rows[0],
        attributes={"nested": [{"value": before}]},
    )
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        peri_scribe.geo.database.reset_database(connection)
        peri_scribe.geo.database.write_snapshot(
            connection,
            peri_scribe.sources.snapshots.SourceFile(
                serial_number=1,
                last_edit_timestamp=1,
            ),
            1,
            1,
            dataclasses.replace(original, rows=(row,)),
            checksum="current",
        )
        cached = peri_scribe.geo.reading.fetch_snapshot_batch(
            connection,
            {pathlib.Path("snapshot"): (1, "current")},
            geometry_pool=spatial_data.geometry_pool.GeometryPool(),
        )[pathlib.Path("snapshot")].rows[0]
        replacement = dataclasses.replace(
            cached,
            attributes={"nested": [{"value": after}]},
        )
        assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(replacement) == (
            peri_scribe.geo.fingerprints.complete_row_fingerprint(replacement)
        )
        if not isinstance(after, tuple):
            assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(
                replacement,
            ) != (cached.evidence_fingerprint)


@pytest.mark.parametrize("field", ["record", "object_id", "source_name"])
def test_row_evidence_fingerprint_detects_replaced_metadata(field: str) -> None:
    row = tests.helpers.factories.peri_scribe.geo.database.contents(1).rows[0]
    attested = dataclasses.replace(
        row,
        evidence_fingerprint=peri_scribe.geo.fingerprints.complete_row_fingerprint(row),
        evidence_basis=peri_scribe.geo.fingerprints.FingerprintBasis(
            record=row.record,
            object_id=row.object_id,
            source_name=row.source_name,
            attributes=copy.deepcopy(row.attributes),
        ),
    )
    replacement = dataclasses.replace(
        attested,
        **{
            field: dataclasses.replace(
                row.record,
                status=peri_scribe.models.FireStatus.INACTIVE,
            )
            if field == "record"
            else 99
            if field == "object_id"
            else "another source",
        },
    )
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(replacement) != (
        attested.evidence_fingerprint
    )


def test_row_evidence_fingerprint_avoids_reencoding_attested_unchanged_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = tests.helpers.factories.peri_scribe.geo.database.contents(1).rows[0]
    expected = peri_scribe.geo.fingerprints.complete_row_fingerprint(row)
    attested = dataclasses.replace(
        row,
        evidence_fingerprint=expected,
        evidence_basis=peri_scribe.geo.fingerprints.FingerprintBasis(
            record=row.record,
            object_id=row.object_id,
            source_name=row.source_name,
            attributes=copy.deepcopy(row.attributes),
        ),
    )
    fresh = unittest.mock.Mock(side_effect=AssertionError("Unexpected full reencoding"))
    monkeypatch.setattr(peri_scribe.geo.fingerprints, "complete_row_fingerprint", fresh)
    assert peri_scribe.geo.fingerprints.row_evidence_fingerprint(attested) == expected
    assert not fresh.called


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (None, None, True),
        ("source", "source", True),
        (True, 1, False),
        (1, 1.0, False),
        (0.0, -0.0, False),
        ([], [1], False),
        ({"a": [1]}, {"a": [1]}, True),
        ({1: 2}, {1: 2}, False),
        ((), (), False),
    ],
)
def test_same_json_value_preserves_native_encoding_distinctions(
    left: object,
    right: object,
    *,
    expected: bool,
) -> None:
    assert peri_scribe.geo.fingerprints.same_json_value(left, right) is expected


@pytest.mark.parametrize("container", [list, dict])
def test_same_json_value_traverses_identical_containers_with_custom_scalars(
    container: type[list[object] | dict[str, object]],
) -> None:
    scalar = tests.helpers.doubles.peri_scribe.geo.fingerprints.NeverEqualInteger(1)
    value = [scalar] if container is list else {"value": scalar}
    assert not peri_scribe.geo.fingerprints.same_json_value(value, value)
    assert scalar.comparisons == [scalar]


def test_same_json_value_preserves_scalar_subclass_equality() -> None:
    scalar = tests.helpers.doubles.peri_scribe.geo.fingerprints.NeverEqualInteger(1)
    assert not peri_scribe.geo.fingerprints.same_json_value(scalar, scalar)
    assert scalar.comparisons == [scalar]


def test_same_json_value_preserves_float_subclass_hex_dispatch() -> None:
    scalar = tests.helpers.doubles.peri_scribe.geo.fingerprints.TracedFloat(-0.0)
    assert peri_scribe.geo.fingerprints.same_json_value(
        {"value": scalar},
        {"value": scalar},
    )
    assert scalar.encodings == ["-0x0.0p+0", "-0x0.0p+0"]


def test_same_json_value_preserves_mapping_subclass_validation_order() -> None:
    events: list[str] = []
    left, right = (
        tests.helpers.doubles.peri_scribe.geo.fingerprints.traced_dictionaries(events)
    )
    assert peri_scribe.geo.fingerprints.same_json_value(left, right)
    assert events == [
        "left:iter",
        "left:keys",
        "right:keys",
        "left:items",
        "right:get:value",
    ]


def test_same_json_value_preserves_strict_list_subclass_iteration() -> None:
    left, right = (
        tests.helpers.doubles.peri_scribe.geo.fingerprints.inconsistent_length_lists()
    )
    with pytest.raises(ValueError, match=r"map\(\).*longer"):
        peri_scribe.geo.fingerprints.same_json_value(left, right)


def test_same_json_value_rechecks_changed_nested_native_containers() -> None:
    template = {"nested": [{"value": [1, 2]}]}
    current = copy.deepcopy(template)
    assert peri_scribe.geo.fingerprints.same_json_value(current, template)
    current["nested"][0]["value"].append(3)
    assert not peri_scribe.geo.fingerprints.same_json_value(current, template)


def test_same_json_value_retains_float_hex_nan_equivalence() -> None:
    first = struct.unpack("!d", bytes.fromhex("7ff8000000000001"))[0]
    second = struct.unpack("!d", bytes.fromhex("fff8000000000002"))[0]
    assert peri_scribe.geo.fingerprints.same_json_value(first, first)
    assert peri_scribe.geo.fingerprints.same_json_value([first], [second])
    assert peri_scribe.geo.fingerprints.same_json_value({"nan": first}, {"nan": second})


@pytest.mark.parametrize(
    ("left", "right"),
    [([1], [2]), ({"a": 1}, {"a": 2}), ({"a": 1}, {"b": 1})],
)
def test_same_json_value_rejects_changed_native_values(
    left: object,
    right: object,
) -> None:
    assert not peri_scribe.geo.fingerprints.same_json_value(left, right)


@pytest.mark.parametrize("unhashable", [True, False])
@pytest.mark.parametrize("container", [None, list, dict])
def test_same_json_value_rejects_unsupported_metaclasses_without_native_dispatch(
    *,
    unhashable: bool,
    container: type[list[object] | dict[str, object]] | None,
) -> None:
    scalar = tests.helpers.doubles.peri_scribe.geo.fingerprints.unusual_metaclass_value(
        unhashable=unhashable,
    )
    value = (
        [scalar]
        if container is list
        else {"value": scalar}
        if container is dict
        else scalar
    )
    assert not peri_scribe.geo.fingerprints.same_json_value(value, value)
