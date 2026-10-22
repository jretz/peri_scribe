"""Live cursors survive diagnostic segment rename and archive publication."""

import compression.zstd
import contextlib
import pathlib
import typing

import peri_scribe.logging
import peri_scribe.monitor.storage


if typing.TYPE_CHECKING:
    import pytest


def test_follower_poll_retains_its_cursor_across_sealing_and_later_appends(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "2026-10.jsonl"
    path.write_bytes(b'{"event":"same"}\n' * 2)
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(tmp_path, tail=False),
    ) as follower:
        assert follower.poll().records == ({"event": "same"},) * 2
        peri_scribe.logging.seal_log(path, force=True)
        path.write_bytes(b'{"event":"later"}\n')
        batch = follower.poll()
        assert batch.records == ({"event": "later"},)
        assert batch.archives == (tmp_path / "2026-10.000000000001.jsonl.zst",)
        assert not batch.errors
        assert follower.poll().records == ()


def test_follower_poll_discovers_plain_segment_after_interrupted_compression(
    tmp_path: pathlib.Path,
) -> None:
    (tmp_path / "2026-10.000000000001.jsonl").write_bytes(b'{"event":"sealed"}\n')
    (tmp_path / "2026-10.jsonl").write_bytes(b'{"event":"active"}\n')
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(tmp_path, tail=False),
    ) as follower:
        assert follower.poll().records == ({"event": "sealed"}, {"event": "active"})


def test_follower_poll_lists_newest_segments_before_the_legacy_prefix(
    tmp_path: pathlib.Path,
) -> None:
    oldest = tmp_path / "2026-09.jsonl.zst"
    first = tmp_path / "2026-09.000000000001.jsonl.zst"
    second = tmp_path / "2026-09.000000000002.jsonl.zst"
    for path in (second, oldest, first):
        path.write_bytes(compression.zstd.compress(b'{"event":"saved"}\n'))
    with contextlib.closing(peri_scribe.monitor.storage.Follower(tmp_path)) as follower:
        assert follower.poll().archives == (second, first, oldest)


def test_follower_poll_drains_a_large_sealed_cursor_before_the_new_tail(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = b'{"event":"same"}\n'
    monkeypatch.setattr(peri_scribe.monitor.storage, "MAXIMUM_READ_BYTES", len(line))
    path = tmp_path / "2026-10.jsonl"
    path.write_bytes(line * 3)
    with contextlib.closing(
        peri_scribe.monitor.storage.Follower(tmp_path, tail=False),
    ) as follower:
        records = list(follower.poll().records)
        peri_scribe.logging.seal_log(path, force=True)
        path.write_bytes(b'{"event":"late"}\n')
        for _ in range(4):
            batch = follower.poll()
            records.extend(batch.records)
            if batch.caught_up:
                break
    assert records == [{"event": "same"}] * 3 + [{"event": "late"}]
