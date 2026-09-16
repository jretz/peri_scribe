"""File observers handle partial writes, rotation, and stable report snapshots."""

import compression.zstd
import contextlib
import datetime
import json
import os
import pathlib
import unittest.mock
from typing import TYPE_CHECKING

import peri_scribe.monitor.storage
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.monitor.events


if TYPE_CHECKING:
    import pytest


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
