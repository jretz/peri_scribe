"""Monthly readers compose legacy archives, sealed components, and active tails."""

import compression.zstd
import datetime
import pathlib

import peri_scribe.log_reading


def test_complete_lines_preserves_legacy_prefix_segment_order_and_active_tail(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-10.jsonl"
    legacy = b'{"event":"legacy"}\n'
    sealed = b'{"event":"same diagnostic"}\n'
    tail = b'{"event":"tail"}\n'
    path.with_suffix(".jsonl.zst").write_bytes(compression.zstd.compress(legacy))
    (tmp_path / "2026-10.000000000002.jsonl").write_bytes(sealed)
    (tmp_path / "2026-10.000000000001.jsonl.zst").write_bytes(
        compression.zstd.compress(sealed),
    )
    path.write_bytes(tail)
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (
        legacy,
        sealed,
        sealed,
        tail,
    )


def test_log_paths_discovers_months_represented_only_by_segments(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "2026-09.000000000001.jsonl.zst").write_bytes(b"archive")
    (tmp_path / "2026-10.000000000001.jsonl").write_bytes(b"plain")
    (tmp_path / "2026-10.not-a-segment.jsonl").write_bytes(b"ignore")
    (tmp_path / "2026-11-fire-updates.jsonl").write_bytes(b"ignore")
    assert peri_scribe.log_reading.log_paths(tmp_path) == (
        tmp_path / "2026-09.jsonl",
        tmp_path / "2026-10.jsonl",
    )
    assert peri_scribe.log_reading.log_paths(
        tmp_path,
        since=datetime.datetime(2026, 10, 1).astimezone(),
    ) == (tmp_path / "2026-10.jsonl",)
