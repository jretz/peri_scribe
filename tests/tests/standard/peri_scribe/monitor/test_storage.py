"""File observers handle partial writes, rotation, and stable report snapshots."""

import compression.zstd
import contextlib
import datetime
import io
import json
import os
import pathlib
import unittest.mock

import pytest

import peri_scribe.monitor.events
import peri_scribe.monitor.storage
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.monitor.events
import tests.helpers.factories.peri_scribe.monitor.status


def test_follower_ignores_fire_update_logs_and_archives(tmp_path: pathlib.Path) -> None:
    (tmp_path / "2026-09-fire-updates.jsonl").write_text('{"name":"Timber"}\n')
    (tmp_path / "2026-08-fire-updates.jsonl.zst").write_bytes(b"not a diagnostic log")
    with contextlib.closing(peri_scribe.monitor.storage.Follower(tmp_path)) as follower:
        batch = follower.poll()
    assert batch.records == ()
    assert batch.archives == ()
    assert batch.errors == ()


@pytest.mark.parametrize("minutes", [[], [-2], [0], [1], [-2, -1], [-1, 0, 0, 1]])
def test_seek_since_keeps_every_record_at_or_after_the_cutoff(
    minutes: list[int],
) -> None:
    cutoff = tests.helpers.factories.peri_scribe.monitor.status.NOW
    records = [
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "café" * (index + 1),
            when=(cutoff + datetime.timedelta(minutes=minute)).astimezone(
                datetime.timezone(datetime.timedelta(hours=index)),
            ),
        )
        for index, minute in enumerate(minutes)
    ]
    with io.BytesIO(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in records
        ).encode(),
    ) as stream:
        peri_scribe.monitor.storage.seek_since(stream, cutoff)
        assert [json.loads(line) for line in stream] == [
            record
            for minute, record in zip(minutes, records, strict=True)
            if minute >= 0
        ]


def test_seek_since_preserves_undated_records_at_the_cutoff() -> None:
    cutoff = tests.helpers.factories.peri_scribe.monitor.status.NOW
    old = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Old",
        when=cutoff - datetime.timedelta(seconds=1),
    )
    recent = tests.helpers.factories.peri_scribe.monitor.status.record("Recent")
    suffix = b'\nnot json\n{"event":"undated"}\n' + json.dumps(recent).encode() + b"\n"
    with io.BytesIO(json.dumps(old).encode() + b"\n" + suffix) as stream:
        peri_scribe.monitor.storage.seek_since(stream, cutoff)
        assert stream.read() == suffix


def test_seek_since_preserves_an_entirely_undated_log() -> None:
    data = b'bad line\n{"event":"undated"}\n'
    with io.BytesIO(data) as stream:
        peri_scribe.monitor.storage.seek_since(
            stream,
            tests.helpers.factories.peri_scribe.monitor.status.NOW,
        )
        assert stream.read() == data


def test_seek_since_does_not_parse_the_entire_old_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = tests.helpers.factories.peri_scribe.monitor.status.NOW
    old = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Old",
        when=cutoff - datetime.timedelta(seconds=1),
    )
    recent = tests.helpers.factories.peri_scribe.monitor.status.record("Recent")
    old_count = 10000
    data = (json.dumps(old) + "\n") * old_count + json.dumps(recent) + "\n"
    parser = unittest.mock.Mock(wraps=peri_scribe.monitor.events.parse_record)
    monkeypatch.setattr(peri_scribe.monitor.events, "parse_record", parser)
    with io.BytesIO(data.encode()) as stream:
        peri_scribe.monitor.storage.seek_since(stream, cutoff)
        assert json.loads(stream.readline()) == recent
    assert parser.call_count < old_count // 100


def test_follower_since_preserves_an_unfinished_utf8_record(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Old",
            when=now - datetime.timedelta(days=3),
        ),
    )
    record = {"timestamp": now.isoformat(), "event": "café"}
    data = json.dumps(record, ensure_ascii=False).encode()
    with path.open("ab") as stream:
        stream.write(data[:-3])
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        assert not follower.poll(since=now - datetime.timedelta(hours=48)).records
        monkeypatch.setattr(
            peri_scribe.monitor.storage,
            "seek_since",
            tests.helpers.doubles.errors.raising_stub(AssertionError("repeated seek")),
        )
        with path.open("ab") as stream:
            stream.write(data[-3:] + b"\n")
        assert follower.poll(since=now - datetime.timedelta(hours=48)).records == (
            record,
        )


def test_open_cursor_closes_the_log_when_seeking_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path)
    with path.open("rb") as stream:
        monkeypatch.setattr(
            pathlib.Path,
            "open",
            unittest.mock.Mock(return_value=stream),
        )
        monkeypatch.setattr(
            peri_scribe.monitor.storage,
            "seek_since",
            tests.helpers.doubles.errors.raising_stub(OSError("seek failed")),
        )
        with pytest.raises(OSError, match="seek failed"):
            peri_scribe.monitor.storage.open_cursor(
                path,
                tail=False,
                since=tests.helpers.factories.peri_scribe.monitor.status.NOW,
            )
        assert stream.closed


def test_follower_waits_without_creating_directories(tmp_path: pathlib.Path) -> None:
    directory = tmp_path / "missing"
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(directory),
    ) as follower:
        assert follower.poll().records == ()
    assert not directory.exists()


def test_follower_buffers_partial_utf8_records(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path)
    data = json.dumps({"event": "café"}, ensure_ascii=False).encode()
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        path.write_bytes(data[:-2])
        assert follower.poll().records == ()
        with path.open("ab") as stream:
            stream.write(data[-2:] + b"\n")
        assert follower.poll().records == ({"event": "café"},)
        assert follower.poll().records == ()


def test_follower_drains_rotated_file_before_new_month(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        {"event": "first"},
    )
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        follower.poll()
        rotated = path.rename(path.with_suffix(".old"))
        with rotated.open("a") as stream:
            stream.write('{"event":"last"}\n')
        rotated.unlink()
        (path.parent / "2026-10.jsonl").write_text('{"event":"new month"}\n')
        assert [entry["event"] for entry in follower.poll().records] == [
            "last",
            "new month",
        ]


def test_follower_restarts_truncated_file(tmp_path: pathlib.Path) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        {"event": "long initial record"},
    )
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        follower.poll()
        path.write_text('{"event":"new"}\n')
        assert follower.poll().records == ({"event": "new"},)


def test_follower_seeks_the_cutoff_after_truncation(tmp_path: pathlib.Path) -> None:
    now = tests.helpers.factories.peri_scribe.monitor.status.NOW
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        tests.helpers.factories.peri_scribe.monitor.status.record("Long" * 1000),
    )
    old = tests.helpers.factories.peri_scribe.monitor.status.record(
        "Old",
        when=now - datetime.timedelta(days=3),
    )
    new = tests.helpers.factories.peri_scribe.monitor.status.record("New")
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        follower.poll(since=now - datetime.timedelta(hours=48))
        path.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
        assert follower.poll(since=now - datetime.timedelta(hours=48)).records == (new,)


def test_follower_bounds_startup_reads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", 30)
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        tmp_path,
        {"event": "first long event"},
        {"event": "middle long event"},
        {"event": "last"},
    )
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        assert follower.poll().records == ({"event": "last"},)


def test_follower_reports_open_failures(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path)
    monkeypatch.setattr(
        peri_scribe.monitor.storage,
        "open_cursor",
        tests.helpers.doubles.errors.raising_stub(PermissionError("blocked")),
    )
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        assert "blocked" in follower.poll().errors[0]


def test_follower_reports_read_failures(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tests.helpers.factories.peri_scribe.monitor.events.write_log(tmp_path)
    monkeypatch.setattr(
        peri_scribe.monitor.storage,
        "read_cursor",
        tests.helpers.doubles.errors.raising_stub(OSError("read failed")),
    )
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(path.parent),
    ) as follower:
        assert follower.poll().errors == ("read failed",)


def test_read_archive_loads_compressed_records(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "2026-08.jsonl.zst"
    with compression.zstd.open(path, "wt") as stream:
        stream.write('\n{"event":"archived"}\n')
    assert peri_scribe.monitor.storage.read_archive(path).records == (
        {"event": "archived"},
    )


def test_read_archive_reports_corruption(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "bad.zst"
    path.write_bytes(b"not zstd")
    assert peri_scribe.monitor.storage.read_archive(path).errors


def test_read_report_uses_file_mtime(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("# Report")
    os.utime(path, (1000000000, 1000000000))
    report = peri_scribe.monitor.storage.read_report(
        path,
        peri_scribe.monitor.storage.Report(),
    )
    assert report.modified == datetime.datetime.fromtimestamp(1000000000).astimezone()
    assert peri_scribe.monitor.storage.read_report(path, report) is report


def test_read_report_detects_atomic_replacement(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "report.md"
    path.write_text("# First")
    previous = peri_scribe.monitor.storage.read_report(
        path,
        peri_scribe.monitor.storage.Report(),
    )
    replacement = tmp_path / "replacement"
    replacement.write_text("# Second")
    replacement.replace(path)
    assert peri_scribe.monitor.storage.read_report(path, previous).content == "# Second"


def test_read_report_retains_previous_snapshot_during_write(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "report.md"
    path.write_text("# First")
    other = tmp_path / "other"
    other.write_text("# Partially written report")
    previous = peri_scribe.monitor.storage.Report(content="# Stable")
    monkeypatch.setattr(
        peri_scribe.monitor.storage.os,
        "fstat",
        unittest.mock.Mock(side_effect=[path.stat(), other.stat()]),
    )
    assert peri_scribe.monitor.storage.read_report(path, previous) is previous


def test_read_report_reports_missing_file(tmp_path: pathlib.Path) -> None:
    assert peri_scribe.monitor.storage.read_report(
        tmp_path / "missing.md",
        peri_scribe.monitor.storage.Report(),
    ).error


def test_read_report_reports_invalid_encoding(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "report.md"
    path.write_bytes(b"\xff")
    assert peri_scribe.monitor.storage.read_report(
        path,
        peri_scribe.monitor.storage.Report(),
    ).error
