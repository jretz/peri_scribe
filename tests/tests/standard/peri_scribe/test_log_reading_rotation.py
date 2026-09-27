"""Monthly readers preserve diagnostic occurrences across interrupted rotation."""

import compression.zstd
import fcntl
import pathlib

import pytest

import peri_scribe.log_reading
import peri_scribe.logging
import tests.helpers.doubles.peri_scribe.log_rotation


def test_complete_lines_includes_archive_before_identical_late_tail(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    line = b'{"event":"repeated diagnostic"}\n'
    path.with_suffix(".jsonl.zst").write_bytes(compression.zstd.compress(line * 2))
    path.write_bytes(line)
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (line,) * 3


def test_complete_lines_reads_published_receipt_without_duplicate_source(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    archive = path.with_suffix(".jsonl.zst")
    older = b'{"event":"older diagnostic"}\n'
    line = b'{"event":"repeated diagnostic"}\n'
    archive.write_bytes(compression.zstd.compress(older))
    path.write_bytes(line * 2)
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target=archive,
        deletion=False,
        after=True,
    )
    with pytest.MonkeyPatch.context() as patch:
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.compress_log(path)
    assert tuple(peri_scribe.log_reading.complete_lines(path)) == (older, line, line)


@pytest.mark.parametrize("suffix", [".jsonl", ".jsonl.zst"])
def test_complete_lines_missing_month_does_not_create_files(
    tmp_path: pathlib.Path,
    suffix: str,
) -> None:
    with pytest.raises(FileNotFoundError):
        tuple(peri_scribe.log_reading.complete_lines(tmp_path / ("2026-01" + suffix)))
    assert tuple(tmp_path.iterdir()) == ()


def test_complete_lines_rejects_invalid_rotation_receipt(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_bytes(b"{}\n")
    receipt = peri_scribe.logging.rotation_receipt_path(path)
    receipt.write_text("invalid receipt")
    with pytest.raises(OSError, match="Invalid JSON"):
        tuple(peri_scribe.log_reading.complete_lines(path))
    assert receipt.read_text() == "invalid receipt"


def test_complete_lines_holds_shared_lock_until_abandoned_iterator_closes(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_bytes(b'{"event":"one"}\n{"event":"two"}\n')
    lock = tmp_path / ".rotation.lock"
    lock.touch()
    with lock.open("rb") as writer:
        lines = peri_scribe.log_reading.complete_lines(path)
        assert next(lines) == b'{"event":"one"}\n'
        with pytest.raises(BlockingIOError):
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lines.close()
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
