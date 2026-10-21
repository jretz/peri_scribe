"""Changed-metadata fixtures and independent byte reads have separate guarantees."""

import hashlib
import os
import pathlib
import time
import unittest.mock

import pytest

import peri_scribe.sources.authentication
import tests.helpers.doubles.peri_scribe.sources.authentication
import tests.helpers.factories.peri_scribe.sources.authentication
from measurement_units import units


@pytest.mark.parametrize(
    "entry_point",
    ["file_digest", "inventory_digest", "inventory_digests"],
)
def test_authentication_reads_fresh_scopes_with_identical_complete_stamps(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_point: str,
) -> None:
    source = tmp_path / "snapshot"
    other = tmp_path / "second"
    source.write_bytes(b"first")
    other.write_bytes(b"fixed")
    original = source.stat()
    stamp = peri_scribe.sources.authentication.file_stamp(source)
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "file_stamp",
        lambda _path: stamp,
    )
    authenticate = getattr(peri_scribe.sources.authentication, entry_point)
    paths = (source, other) if entry_point == "inventory_digests" else (source,)
    checksums = []
    for contents in (b"first", b"other"):
        source.write_bytes(contents)
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert peri_scribe.sources.authentication.file_stamp(source) == stamp
        with peri_scribe.sources.authentication.scope(tmp_path):
            if entry_point == "inventory_digests":
                current = authenticate(paths)
                assert current == tuple(
                    hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
                )
                checksums.append(current[0])
            else:
                current = authenticate(source)
                assert current == hashlib.sha256(contents).hexdigest()
                checksums.append(current)
    assert checksums[0] != checksums[1]
    assert sorted(recorder.paths) == sorted((*paths, *paths))


@pytest.mark.parametrize("explicit_timestamps", [False, True])
def test_rewrite_with_changed_ctime_waits_for_observed_change_and_restores_times(
    tmp_path: pathlib.Path,
    *,
    explicit_timestamps: bool,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    original = source.stat()
    advanced = unittest.mock.Mock(wraps=original)
    advanced.st_ctime_ns = original.st_ctime_ns + 1
    selected = (original.st_atime_ns, original.st_mtime_ns)
    if explicit_timestamps:
        selected = (
            selected[0],
            selected[1] - int((1 * units.seconds).m_as("nanoseconds")),
        )
    statuses = [original, original, advanced]
    with (
        unittest.mock.patch.object(
            pathlib.Path,
            "stat",
            side_effect=statuses,
        ) as observed,
        unittest.mock.patch.object(
            time,
            "monotonic",
            side_effect=[
                0,
                (
                    tests.helpers.factories.peri_scribe.sources.authentication.CTIME_CHANGE_TIMEOUT
                    / 2
                ).m_as("seconds"),
            ],
        ),
        unittest.mock.patch.object(time, "sleep") as pause,
        unittest.mock.patch.object(os, "utime", wraps=os.utime) as restore,
    ):
        if explicit_timestamps:
            tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
                source,
                b"other",
                timestamps=selected,
            )
        else:
            tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
                source,
                b"other",
            )
    assert observed.call_count == len(statuses)
    assert restore.call_args_list == [
        unittest.mock.call(source, ns=selected),
        unittest.mock.call(source, ns=selected),
    ]
    pause.assert_called_once_with(
        tests.helpers.factories.peri_scribe.sources.authentication.CTIME_POLL_INTERVAL.m_as(
            "seconds",
        ),
    )
    changed = source.stat()
    assert changed.st_atime_ns == selected[0]
    assert changed.st_mtime_ns == selected[1]
    assert source.read_bytes() == b"other"


def test_rewrite_with_changed_ctime_timeout_reports_complete_identity(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    original = source.stat()
    with (
        unittest.mock.patch.object(pathlib.Path, "stat", return_value=original),
        unittest.mock.patch.object(
            time,
            "monotonic",
            side_effect=[
                0,
                (
                    tests.helpers.factories.peri_scribe.sources.authentication.CTIME_CHANGE_TIMEOUT
                    * 2
                ).m_as("seconds"),
            ],
        ),
        unittest.mock.patch.object(time, "sleep") as pause,
        pytest.raises(
            AssertionError,
            match=r"File ctime did not change.*before/after identity",
        ) as raised,
    ):
        tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
            source,
            b"other",
        )
    message = str(raised.value)
    assert str(source) in message
    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"):
        assert field in message
    pause.assert_not_called()
    assert source.read_bytes() == b"other"
