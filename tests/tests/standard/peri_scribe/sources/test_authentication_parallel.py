"""Parallel reads retain fresh ordered authentication and complete worker lifetimes."""

from __future__ import annotations

import concurrent.futures
import contextvars
import dataclasses
import hashlib
import os
import pathlib
import threading
import unittest.mock

import pytest

import peri_scribe.sources.authentication
import tests.helpers.doubles.peri_scribe.sources.authentication
import tests.helpers.factories.peri_scribe.sources.authentication


def test_inventory_digests_reads_fresh_bytes_and_retains_order_across_scopes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    expected = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    for _ in range(2):
        with peri_scribe.sources.authentication.scope(tmp_path):
            owner = peri_scribe.sources.authentication.CURRENT.get()
            assert owner is not None
            with unittest.mock.patch.object(pathlib.Path, "resolve") as resolve:
                assert peri_scribe.sources.authentication.inventory_digests(paths) == (
                    expected
                )
            resolve.assert_not_called()
            assert set(owner.pending) == set(paths)
            assert not owner.values
            assert tuple(
                map(peri_scribe.sources.authentication.file_digest, paths),
            ) == (expected)
            assert not owner.pending
    assert sorted(recorder.paths) == sorted((*paths, *paths))


def test_inventory_digests_mixed_and_duplicate_requests_use_canonical_admission(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        peri_scribe.sources.authentication.file_digest(paths[0])
        peri_scribe.sources.authentication.inventory_digest(paths[1])
        requested = (*paths, paths[-1], paths[0], paths[-2])
        expected = tuple(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in requested
        )
        assert (
            peri_scribe.sources.authentication.inventory_digests(requested) == expected
        )
        assert (
            peri_scribe.sources.authentication.inventory_digests(requested) == expected
        )
    assert sorted(recorder.paths) == sorted(paths)


@pytest.mark.parametrize("count", [0, 1])
def test_inventory_digests_tiny_inventories_avoid_workers(
    tmp_path: pathlib.Path,
    count: int,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
        count,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        unittest.mock.patch.object(
            concurrent.futures,
            "ThreadPoolExecutor",
            side_effect=AssertionError("unexpected worker"),
        ),
    ):
        assert peri_scribe.sources.authentication.inventory_digests(paths) == tuple(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        )


@pytest.mark.parametrize("processors", [None, 1, 2, 20])
def test_read_inventory_evidence_caps_workers_by_available_processors(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    processors: int | None,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    executor = concurrent.futures.ThreadPoolExecutor
    monkeypatch.setattr(os, "cpu_count", lambda: processors)
    with unittest.mock.patch.object(
        concurrent.futures,
        "ThreadPoolExecutor",
        wraps=executor,
    ) as observed:
        evidence = peri_scribe.sources.authentication.read_inventory_evidence(paths)
    assert tuple(evidence[path].checksum for path in paths) == tuple(
        hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    )
    if processors is None or processors == 1:
        observed.assert_not_called()
    else:
        observed.assert_called_once_with(max_workers=min(4, processors))


def test_inventory_digests_workers_never_borrow_scope_and_join_before_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    reader = tests.helpers.doubles.peri_scribe.sources.authentication.ControlledReader(
        read=peri_scribe.sources.authentication.read_file_digest,
        blocked=paths[0],
        failing=paths[1],
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    monkeypatch.setattr(peri_scribe.sources.authentication, "read_file_digest", reader)
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as caller,
    ):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        future = caller.submit(
            contextvars.copy_context().run,
            peri_scribe.sources.authentication.inventory_digests,
            paths,
        )
        try:
            assert reader.failed.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
            assert not owner.pending
            assert not owner.values
        finally:
            reader.released.set()
        with pytest.raises(OSError, match="controlled source failure"):
            future.result(timeout=5)
        assert paths[0] in reader.finished
        assert not owner.pending
    assert reader.owners
    assert all(value is None for value in reader.owners)


def test_read_inventory_batch_cancellation_stops_before_reading(
    tmp_path: pathlib.Path,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    cancelled = threading.Event()
    cancelled.set()
    with (
        unittest.mock.patch.object(
            peri_scribe.sources.authentication,
            "read_file_digest",
            side_effect=AssertionError("unexpected read"),
        ),
        pytest.raises(concurrent.futures.CancelledError),
    ):
        peri_scribe.sources.authentication.read_inventory_batch(paths, cancelled)


@pytest.mark.parametrize("change", ["bytes", "replace"])
def test_publish_inventory_evidence_rejects_mutation_without_partial_publication(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        evidence = peri_scribe.sources.authentication.read_inventory_evidence(paths)
        original = paths[-1].stat()
        if change == "replace":
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"other")
            replacement.replace(paths[-1])
        else:
            paths[-1].write_bytes(b"other")
        os.utime(paths[-1], ns=(original.st_atime_ns, original.st_mtime_ns))
        with pytest.raises(OSError, match="Source changed while authenticating"):
            peri_scribe.sources.authentication.publish_inventory_evidence(
                owner,
                evidence,
            )
        assert not owner.pending
        assert not owner.values


@pytest.mark.parametrize("foreign_process", [False, True])
def test_publish_inventory_evidence_rejects_expired_or_foreign_owner_before_lock(
    tmp_path: pathlib.Path,
    *,
    foreign_process: bool,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        evidence = peri_scribe.sources.authentication.read_inventory_evidence(paths)
        if foreign_process:
            owner = dataclasses.replace(owner, process=os.getpid() + 1)
        else:
            owner.active.clear()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as caller:
            owner.lock.acquire()
            try:
                future = caller.submit(
                    peri_scribe.sources.authentication.publish_inventory_evidence,
                    owner,
                    evidence,
                )
                with pytest.raises(OSError, match="scope expired"):
                    future.result(timeout=5)
            finally:
                owner.lock.release()
        assert not owner.pending


def test_publish_inventory_evidence_rechecks_liveness_after_lock(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        with (
            unittest.mock.patch.object(
                peri_scribe.sources.authentication.Scope,
                "live",
                side_effect=[True, False],
            ),
            pytest.raises(OSError, match="scope expired"),
        ):
            peri_scribe.sources.authentication.publish_inventory_evidence(owner, {})
        assert not owner.pending


@pytest.mark.parametrize("state", ["unowned", "expired", "foreign"])
def test_inventory_digests_ineligible_owner_uses_fresh_serial_reads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    reader = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(peri_scribe.sources.authentication, "read_file_digest", reader)
    with peri_scribe.sources.authentication.scope(tmp_path):
        original = peri_scribe.sources.authentication.CURRENT.get()
        assert original is not None
        owner = original
        if state == "unowned":
            owner = None
        elif state == "expired":
            original.active.clear()
        else:
            owner = dataclasses.replace(original, process=os.getpid() + 1)
        token = peri_scribe.sources.authentication.CURRENT.set(owner)
        try:
            with unittest.mock.patch.object(
                concurrent.futures,
                "ThreadPoolExecutor",
                side_effect=AssertionError("unexpected worker"),
            ):
                assert peri_scribe.sources.authentication.inventory_digests(paths) == (
                    tuple(
                        hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
                    )
                )
        finally:
            peri_scribe.sources.authentication.CURRENT.reset(token)
    assert reader.paths == list(paths)


def test_inventory_digests_rechecks_liveness_before_fresh_selection(
    tmp_path: pathlib.Path,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        unittest.mock.patch.object(
            peri_scribe.sources.authentication.Scope,
            "live",
            side_effect=[True, False],
        ),
        pytest.raises(OSError, match="scope expired"),
    ):
        peri_scribe.sources.authentication.inventory_digests(paths)


def test_read_inventory_evidence_empty_batch_needs_no_worker() -> None:
    assert peri_scribe.sources.authentication.read_inventory_evidence(()) == {}


def test_inventory_digests_caller_interruption_joins_before_scope_cleanup(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    reader = tests.helpers.doubles.peri_scribe.sources.authentication.ControlledReader(
        read=peri_scribe.sources.authentication.read_file_digest,
        blocked=paths[0],
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        reader,
    )
    monkeypatch.setattr(concurrent.futures, "as_completed", reader.interrupt)
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as caller,
    ):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        future = caller.submit(
            contextvars.copy_context().run,
            peri_scribe.sources.authentication.inventory_digests,
            paths,
        )
        try:
            assert reader.entered.wait(timeout=5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.05)
            assert owner.live()
            assert not owner.pending
        finally:
            reader.released.set()
        with pytest.raises(KeyboardInterrupt, match="controlled caller interruption"):
            future.result(timeout=5)
        assert paths[0] in reader.finished
    assert not owner.live()
    assert not owner.pending


def test_inventory_digests_rejects_expiry_during_worker_read(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    reader = tests.helpers.doubles.peri_scribe.sources.authentication.ControlledReader(
        read=peri_scribe.sources.authentication.read_file_digest,
        blocked=paths[0],
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        reader,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as caller,
    ):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        future = caller.submit(
            contextvars.copy_context().run,
            peri_scribe.sources.authentication.inventory_digests,
            paths,
        )
        try:
            assert reader.entered.wait(timeout=5)
            owner.active.clear()
        finally:
            reader.released.set()
        with pytest.raises(OSError, match="scope expired"):
            future.result(timeout=5)
        assert not owner.pending
        assert paths[0] in reader.finished


def test_inventory_digests_rejects_change_while_hashing_without_batch_publication(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = tests.helpers.factories.peri_scribe.sources.authentication.inventory(
        tmp_path,
    )
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
        replacement=b"other",
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        with pytest.raises(OSError, match="Source changed while authenticating"):
            peri_scribe.sources.authentication.inventory_digests(paths)
        assert not owner.pending
        assert not owner.values


@pytest.mark.parametrize("outside", [False, True])
def test_inventory_digests_pending_admission_rechecks_retargeted_parent_symlink(
    tmp_path: pathlib.Path,
    *,
    outside: bool,
) -> None:
    directory = tmp_path / "sources"
    first = directory / "first"
    second = tmp_path / "outside" if outside else directory / "second"
    first.mkdir(parents=True)
    second.mkdir()
    original_paths = (
        tests.helpers.factories.peri_scribe.sources.authentication.inventory(
            first,
        )
    )
    changed_paths = (
        tests.helpers.factories.peri_scribe.sources.authentication.inventory(
            second,
        )
    )
    for path in changed_paths:
        path.write_bytes(b"changed")
    parent = directory / "link"
    parent.symlink_to(first, target_is_directory=True)
    paths = tuple(parent / path.name for path in original_paths)
    with peri_scribe.sources.authentication.scope(directory):
        original = peri_scribe.sources.authentication.inventory_digests(paths)
        parent.unlink()
        parent.symlink_to(second, target_is_directory=True)
        current = peri_scribe.sources.authentication.inventory_digests(paths)
    assert original != current
    assert current == (hashlib.sha256(b"changed").hexdigest(),) * len(paths)
