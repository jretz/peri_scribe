"""Interrupted compression preserves diagnostic occurrence counts across retries."""

import compression.zstd
import datetime
import pathlib
import unittest.mock

import pytest
import time_machine

import peri_scribe.logging
import tests.helpers.doubles.peri_scribe.log_rotation


def test_compress_log_retry_preserves_identical_diagnostic_occurrences(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    record = '{"event":"command finished"}\n'
    path.write_text(record * 2, encoding="utf-8")
    with (
        unittest.mock.patch.object(
            pathlib.Path,
            "unlink",
            side_effect=OSError("interrupted source removal"),
        ),
        pytest.raises(OSError, match="interrupted source removal"),
    ):
        peri_scribe.logging.compress_log(path)
    peri_scribe.logging.compress_log(path)
    with compression.zstd.open(path.with_suffix(".jsonl.zst"), "rt") as archive:
        assert archive.read() == record * 2


def test_compress_log_preserves_identical_late_arrivals(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-01.jsonl"
    record = '{"event":"command finished"}\n'
    path.write_text(record, encoding="utf-8")
    peri_scribe.logging.compress_log(path)
    path.write_text(record, encoding="utf-8")
    peri_scribe.logging.compress_log(path)
    with compression.zstd.open(path.with_suffix(".jsonl.zst"), "rt") as archive:
        assert archive.read() == record * 2


@pytest.mark.parametrize("boundary", ["receipt", "archive", "source", "retire"])
@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_compress_log_recovers_every_durable_boundary(
    tmp_path: pathlib.Path,
    boundary: str,
    *,
    after: bool,
    existing: bool,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    archive = path.with_suffix(".jsonl.zst")
    receipt = peri_scribe.logging.rotation_receipt_path(path)
    record = '{"event":"identical diagnostic"}\n'
    if existing:
        archive.write_bytes(compression.zstd.compress(record.encode()))
    path.write_text(record * 2, encoding="utf-8")
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target={
            "receipt": receipt,
            "archive": archive,
            "source": path,
            "retire": receipt,
        }[boundary],
        deletion=boundary in {"source", "retire"},
        after=after,
    )
    with pytest.MonkeyPatch.context() as patch:
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.compress_log(path)
    assert interruption.reached
    if path.exists() or receipt.exists():
        peri_scribe.logging.compress_log(path)
    with compression.zstd.open(archive, "rt") as stream:
        assert stream.read() == record * (2 + existing)
    assert list(tmp_path.iterdir()) == [archive]


def test_append_monthly_records_recovers_removed_source_before_late_append(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    record = '{"event":"identical diagnostic"}\n'
    path.write_text(record, encoding="utf-8")
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target=path,
        deletion=True,
        after=True,
    )
    with pytest.MonkeyPatch.context() as patch:
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.compress_log(path)
    with time_machine.travel("2026-09-01T12:00:00Z", tick=False):
        peri_scribe.logging.append_monthly_records(
            tmp_path,
            ({"event": "identical diagnostic"},),
            timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        )
    assert not peri_scribe.logging.rotation_receipt_path(path).exists()
    assert path.read_text(encoding="utf-8").count("identical diagnostic") == 1
    with compression.zstd.open(path.with_suffix(".jsonl.zst"), "rt") as stream:
        assert stream.read() == record


@pytest.mark.parametrize("payload", [b"invalid", b"{}", b'{"version":2}'])
def test_recover_rotation_refuses_malformed_receipts(
    tmp_path: pathlib.Path,
    payload: bytes,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    path.write_bytes(b"preserved source\n")
    receipt = peri_scribe.logging.rotation_receipt_path(path)
    receipt.write_bytes(payload)
    with pytest.raises(ValueError, match="validation error"):
        peri_scribe.logging.recover_rotation(path)
    assert path.read_bytes() == b"preserved source\n"
    assert receipt.read_bytes() == payload


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("changed", ["source", "archive"])
def test_recover_rotation_refuses_files_that_disagree_with_receipt(
    tmp_path: pathlib.Path,
    changed: str,
    *,
    committed: bool,
) -> None:
    path = tmp_path / "2026-01.jsonl"
    archive = path.with_suffix(".jsonl.zst")
    path.write_bytes(b"original source\n")
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target=archive,
        deletion=False,
        after=committed,
    )
    with pytest.MonkeyPatch.context() as patch:
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.compress_log(path)
    target = path if changed == "source" else archive
    target.write_bytes(b"unrelated new contents\n")
    with pytest.raises(ValueError, match="Rotation"):
        peri_scribe.logging.recover_rotation(path)
    assert target.read_bytes() == b"unrelated new contents\n"
    assert peri_scribe.logging.rotation_receipt_path(path).exists()


def test_compress_log_rejects_missing_source_without_receipt(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        peri_scribe.logging.compress_log(tmp_path / "2026-01.jsonl")
