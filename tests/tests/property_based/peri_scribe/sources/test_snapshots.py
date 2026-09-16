"""Tests for peri_scribe.sources.snapshots."""

from __future__ import annotations

import hypothesis
import hypothesis.strategies

import peri_scribe.sources.snapshots


@hypothesis.given(
    serial=hypothesis.strategies.integers(0, 10**9),
    timestamp=hypothesis.strategies.integers(0, 2**63 - 1),
)
def test_source_file_from_path_round_trips_generated_snapshot_names(
    serial: int,
    timestamp: int,
) -> None:
    source_file = peri_scribe.sources.snapshots.SourceFile(
        serial_number=serial,
        last_edit_timestamp=timestamp,
    )
    assert (
        peri_scribe.sources.snapshots.SourceFile.from_path(
            source_file.relative_path,
        )
        == source_file
    )


@hypothesis.given(
    requests=hypothesis.strategies.lists(
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(0, 5),
            hypothesis.strategies.booleans(),
        ),
        max_size=30,
    ),
)
def test_next_serial_number_matches_snapshot_history(
    requests: list[tuple[int, bool]],
) -> None:
    timestamps: list[int] = []
    files: list[peri_scribe.sources.snapshots.SourceFile] = []
    for timestamp, reuse in requests:
        serial = peri_scribe.sources.snapshots.next_serial_number(
            reversed(files),
            timestamp,
            reuse_same_timestamp=reuse,
        )
        if reuse and timestamp in timestamps:
            assert serial == len(timestamps) - 1 - timestamps[::-1].index(timestamp)
        else:
            assert serial == len(timestamps)
            timestamps.append(timestamp)
            files.append(
                peri_scribe.sources.snapshots.SourceFile(
                    serial_number=serial,
                    last_edit_timestamp=timestamp,
                ),
            )
