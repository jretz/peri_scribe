"""Sealed diagnostics preserve occurrences through recovery and later appends."""

import compression.zstd
import datetime
import pathlib

import pytest
import time_machine

import peri_scribe.log_reading
import peri_scribe.logging
import tests.helpers.doubles.peri_scribe.log_rotation


def test_append_monthly_records_bounds_the_live_tail_without_rewriting_segments(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.logging, "MAXIMUM_LOG_SEGMENT_BYTES", 1)
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    path = tmp_path / "2026-10.jsonl"
    with time_machine.travel(now, tick=False):
        peri_scribe.logging.append_monthly_records(tmp_path, ({"event": "first"},))
        first = path.read_bytes()
        peri_scribe.logging.append_monthly_records(tmp_path, ({"event": "second"},))
        second = path.read_bytes()
        archive = tmp_path / "2026-10.000000000001.jsonl.zst"
        before = archive.read_bytes(), archive.stat().st_mtime_ns
        peri_scribe.logging.append_monthly_records(tmp_path, ({"event": "third"},))
    assert (archive.read_bytes(), archive.stat().st_mtime_ns) == before
    expected_segments = 2
    assert len(peri_scribe.logging.segment_paths(path)) == expected_segments
    assert b"third" in path.read_bytes()
    assert b"second" not in path.read_bytes()
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (
        first,
        second,
        path.read_bytes(),
    )


@pytest.mark.parametrize(
    "boundary",
    ["rename", "receipt", "archive", "source", "retire"],
)
@pytest.mark.parametrize("after", [False, True])
def test_append_monthly_records_recovers_every_segment_boundary(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    *,
    after: bool,
) -> None:
    monkeypatch.setattr(peri_scribe.logging, "MAXIMUM_LOG_SEGMENT_BYTES", 1)
    now = datetime.datetime(2026, 10, 22, tzinfo=datetime.UTC)
    path = tmp_path / "2026-10.jsonl"
    segment = tmp_path / "2026-10.000000000001.jsonl"
    archive = segment.with_suffix(".jsonl.zst")
    receipt = peri_scribe.logging.rotation_receipt_path(segment)
    original = b'{"event":"same diagnostic"}\n' * 2
    path.write_bytes(original)
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target={
            "rename": segment,
            "receipt": receipt,
            "archive": archive,
            "source": segment,
            "retire": receipt,
        }[boundary],
        deletion=boundary in {"source", "retire"},
        after=after,
    )
    with (
        time_machine.travel(now, tick=False),
        pytest.MonkeyPatch.context() as patch,
    ):
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.append_monthly_records(tmp_path, ({"event": "later"},))
    assert interruption.reached
    assert b"".join(peri_scribe.log_reading.complete_lines(path)) == original
    with time_machine.travel(now, tick=False):
        peri_scribe.logging.append_monthly_records(tmp_path, ({"event": "later"},))
    lines = tuple(peri_scribe.log_reading.complete_lines(path))
    assert lines[:2] == (original[: len(original) // 2],) * 2
    expected_records = 3
    assert len(lines) == expected_records
    assert b"later" in lines[-1]
    assert not receipt.exists()


def test_seal_log_keeps_an_incomplete_record_available_to_its_writer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.logging, "MAXIMUM_LOG_SEGMENT_BYTES", 1)
    path = tmp_path / "2026-10.jsonl"
    original = b'{"event":"unfinished'
    path.write_bytes(original)
    peri_scribe.logging.seal_log(path)
    assert path.read_bytes() == original
    assert peri_scribe.logging.segment_paths(path) == ()


def test_seal_log_ignores_missing_and_empty_tails(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-10.jsonl"
    peri_scribe.logging.seal_log(path, force=True)
    path.touch()
    peri_scribe.logging.seal_log(path, force=True)
    assert list(tmp_path.iterdir()) == [path]


def test_append_monthly_records_closes_segmented_month_after_its_sealed_prefix(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    segment = tmp_path / "2026-01.000000000001.jsonl.zst"
    older = b'{"event":"older"}\n'
    later = b'{"event":"later"}\n'
    segment.write_bytes(compression.zstd.compress(older))
    path.write_bytes(later)
    with time_machine.travel("2026-10-22T00:00:00Z", tick=False):
        peri_scribe.logging.append_monthly_records(tmp_path, ())
    assert not path.exists()
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (older, later)
    expected_segments = 2
    assert len(peri_scribe.logging.segment_paths(path)) == expected_segments


def test_contains_batch_finds_a_batch_in_a_sealed_component(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-10.jsonl"
    segment = tmp_path / "2026-10.000000000001.jsonl.zst"
    segment.write_bytes(compression.zstd.compress(b'{"batch_id":"saved"}\n'))
    assert peri_scribe.logging.contains_batch(path, "saved")
    assert not peri_scribe.logging.contains_batch(path, "missing")


def test_segment_paths_orders_large_ordinals_numerically(
    tmp_path: pathlib.Path,
) -> None:
    first = tmp_path / "2026-10.999999999999.jsonl.zst"
    second = tmp_path / "2026-10.1000000000000.jsonl.zst"
    first.touch()
    second.touch()
    assert peri_scribe.logging.segment_paths(tmp_path / "2026-10.jsonl") == (
        first.with_suffix(""),
        second.with_suffix(""),
    )
