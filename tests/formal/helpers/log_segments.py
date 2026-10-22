"""Materialize every checked segment boundary for the real coherent monthly reader."""

import compression.zstd
import hashlib
import pathlib
import re

import peri_scribe.log_reading
import peri_scribe.logging
import tests.formal.helpers.log_rotation


def segment_sequences(value: str) -> tuple[tuple[int, ...], ...]:
    """Decode the checked sequence of immutable segment occurrence sequences.

    Args:
        value: A TLC-rendered nested sequence.

    Returns:
        Every segment's occurrence sequence in publication order.
    """
    if value == "<<>>":
        return ()
    return tuple(
        tests.formal.helpers.log_rotation.numbers(body)
        for body in re.findall(r"<<([^<>]*)>>", value)
    )


def contents(sequence: tuple[int, ...]) -> bytes:
    """Bind each formal occurrence to concrete diagnostics without value deduplication.

    Args:
        sequence: Ordered diagnostic occurrence values.

    Returns:
        Exact UTF-8 JSONL bytes, including repeated records.
    """
    return b"".join(
        tests.formal.helpers.log_rotation.LINES[value] for value in sequence
    )


def observe(state: dict[str, str], directory: pathlib.Path) -> None:
    """Read actual files at one checked rename, receipt or retirement boundary.

    Args:
        state: One state from the complete checked segmentation graph.
        directory: A new isolated log directory for this concrete observation.
    """
    directory.mkdir()
    path = directory / "2026-10.jsonl"
    path.with_suffix(".jsonl.zst").write_bytes(
        compression.zstd.compress(contents((2,))),
    )
    active = tests.formal.helpers.log_rotation.numbers(state["active"])
    if active:
        path.write_bytes(contents(active))
    archived = set(tests.formal.helpers.log_rotation.numbers(state["archives"]))
    removed = set(tests.formal.helpers.log_rotation.numbers(state["removed"]))
    receipts = set(tests.formal.helpers.log_rotation.numbers(state["receipts"]))
    for index, sequence in enumerate(segment_sequences(state["sealed"]), start=1):
        segment = directory / f"2026-10.{index:012d}.jsonl"
        source = contents(sequence)
        encoded = compression.zstd.compress(source)
        if index not in removed:
            segment.write_bytes(source)
        if index in archived:
            segment.with_suffix(".jsonl.zst").write_bytes(encoded)
        if index in receipts:
            receipt = peri_scribe.logging.RotationReceipt(
                source_checksum=hashlib.sha256(source).hexdigest(),
                archive_checksum=None,
                target_checksum=hashlib.sha256(encoded).hexdigest(),
            )
            peri_scribe.logging.rotation_receipt_path(segment).write_bytes(
                receipt.model_dump_json().encode(),
            )
    observed = b"".join(peri_scribe.log_reading.complete_lines(path))
    expected = contents(tests.formal.helpers.log_rotation.numbers(state["expected"]))
    assert observed == expected
