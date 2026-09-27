"""Physical monthly representations must preserve the historical acreage baseline."""

import datetime
import pathlib

import pydantic
import pytest

import peri_scribe.logging
import peri_scribe.updates
import tests.helpers.doubles.peri_scribe.log_rotation
import tests.helpers.factories.peri_scribe.updates
from measurement_units import units


def test_read_entries_preserves_archive_then_late_tail_at_equal_times(
    tmp_path: pathlib.Path,
) -> None:
    timestamp = datetime.datetime(2026, 8, 31, 23, 59, 59, tzinfo=datetime.UTC)
    records = tuple(
        tests.helpers.factories.peri_scribe.updates.entry(timestamp, area * units.acres)
        for area in (100, 200)
    )
    for suffix, record in zip((".zst", ""), records, strict=True):
        tests.helpers.factories.peri_scribe.updates.write_log(
            tmp_path / "logs" / f"2026-08-fire-updates.jsonl{suffix}",
            [record],
        )

    assert peri_scribe.updates.read_entries(tmp_path) == records


def test_read_entries_preserves_historical_late_tail_as_current_baseline(
    tmp_path: pathlib.Path,
) -> None:
    old = datetime.datetime(2026, 8, 31, 23, 59, 59, tzinfo=datetime.UTC)
    now = datetime.datetime(2026, 9, 26, 12, tzinfo=datetime.UTC)
    for filename, timestamp, area in (
        ("2026-08-fire-updates.jsonl.zst", old, 100),
        ("2026-08-fire-updates.jsonl", old, 200),
        ("2026-09-fire-updates.jsonl", now, 150),
    ):
        tests.helpers.factories.peri_scribe.updates.write_log(
            tmp_path / "logs" / filename,
            [
                tests.helpers.factories.peri_scribe.updates.entry(
                    timestamp,
                    area * units.acres,
                ),
            ],
        )

    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        now,
    )

    assert len(snapshot.updates) == 1
    assert snapshot.updates[0].mapped_area == peri_scribe.updates.Acreage(value=150)
    assert snapshot.updates[0].previous_mapped_area == peri_scribe.updates.Acreage(
        value=200,
    )


@pytest.mark.parametrize("after", [False, True])
def test_read_entries_authenticates_interrupted_rotation_without_replaying_source(
    tmp_path: pathlib.Path,
    *,
    after: bool,
) -> None:
    timestamp = datetime.datetime(2026, 8, 31, 23, 59, 59, tzinfo=datetime.UTC)
    records = tuple(
        tests.helpers.factories.peri_scribe.updates.entry(timestamp, area * units.acres)
        for area in (100, 200)
    )
    plain = tmp_path / "logs" / "2026-08-fire-updates.jsonl"
    archive = plain.with_suffix(".jsonl.zst")
    for path, record in zip((archive, plain), records, strict=True):
        tests.helpers.factories.peri_scribe.updates.write_log(path, [record])
    interruption = tests.helpers.doubles.peri_scribe.log_rotation.Interruption(
        target=archive,
        deletion=False,
        after=after,
    )
    with pytest.MonkeyPatch.context() as patch:
        interruption.install(patch)
        with pytest.raises(tests.helpers.doubles.peri_scribe.log_rotation.ProcessLoss):
            peri_scribe.logging.compress_log(plain)
    assert interruption.reached
    before = {path: path.read_bytes() for path in plain.parent.iterdir()}

    assert peri_scribe.updates.read_entries(tmp_path) == records
    assert {path: path.read_bytes() for path in plain.parent.iterdir()} == before


def test_read_entries_rejects_unauthenticated_rotation(tmp_path: pathlib.Path) -> None:
    plain = tmp_path / "logs" / "2026-08-fire-updates.jsonl"
    record = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    tests.helpers.factories.peri_scribe.updates.write_log(plain, [record])
    receipt = peri_scribe.logging.RotationReceipt(
        source_checksum="wrong source",
        archive_checksum=None,
        target_checksum="absent",
    )
    peri_scribe.logging.rotation_receipt_path(plain).write_text(
        receipt.model_dump_json(),
    )

    with pytest.raises(OSError, match="does not authenticate"):
        peri_scribe.updates.read_entries(tmp_path)


def test_read_entries_preserves_equal_late_occurrences(tmp_path: pathlib.Path) -> None:
    record = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    for suffix in ("", ".zst"):
        tests.helpers.factories.peri_scribe.updates.write_log(
            tmp_path / "logs" / f"2026-08-fire-updates.jsonl{suffix}",
            [record],
        )

    assert peri_scribe.updates.read_entries(tmp_path) == (record, record)


@pytest.mark.parametrize("content", ["{", "{}\n"])
def test_read_entries_rejects_invalid_authoritative_records(
    tmp_path: pathlib.Path,
    content: str,
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-08-fire-updates.jsonl").write_text(content)

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.read_entries(tmp_path)


def test_read_entries_accepts_complete_legacy_record_without_final_newline(
    tmp_path: pathlib.Path,
) -> None:
    record = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-08-fire-updates.jsonl").write_text(record.model_dump_json())

    assert peri_scribe.updates.read_entries(tmp_path) == (record,)
