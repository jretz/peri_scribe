"""Byte evidence remains fresh across independent and expired source scopes."""

from __future__ import annotations

import concurrent.futures
import contextlib
import contextvars
import dataclasses
import hashlib
import os
import pathlib
import unittest.mock

import pytest

import peri_scribe.preparation
import peri_scribe.sources.authentication
import tests.helpers.doubles.peri_scribe.sources.authentication
import tests.helpers.factories.peri_scribe.sources.authentication


def test_file_digest_reads_independent_invocations_freshly(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
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
            assert peri_scribe.sources.authentication.file_digest(source) == (
                hashlib.sha256(b"source").hexdigest()
            )
            peri_scribe.sources.authentication.file_digest(source)
    assert recorder.paths == [source, source]


@pytest.mark.parametrize("change", ["same_timestamp", "replacement", "size"])
def test_file_digest_reauthenticates_changed_owned_inputs(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    original = source.stat()
    with peri_scribe.sources.authentication.scope(tmp_path):
        first = peri_scribe.sources.authentication.file_digest(source)
        if change == "replacement":
            temporary = source.with_name("replacement")
            temporary.write_bytes(b"other")
            temporary.replace(source)
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        else:
            tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
                source,
                b"other" if change == "same_timestamp" else b"longer",
                timestamps=(original.st_atime_ns, original.st_mtime_ns),
            )
        if change == "same_timestamp":
            changed = source.stat()
            assert changed.st_dev == original.st_dev
            assert changed.st_ino == original.st_ino
            assert changed.st_size == original.st_size
            assert changed.st_mtime_ns == original.st_mtime_ns
            assert changed.st_ctime_ns != original.st_ctime_ns
        second = peri_scribe.sources.authentication.file_digest(source)
    assert first != second
    assert second == hashlib.sha256(source.read_bytes()).hexdigest()


def test_file_digest_rejects_changes_during_authentication(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
        replacement=b"other",
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        pytest.raises(OSError, match="Source changed while authenticating"),
    ):
        peri_scribe.sources.authentication.file_digest(source)


def test_file_digest_does_not_cache_outside_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "outside"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path / "sources"):
        for _ in range(2):
            peri_scribe.sources.authentication.file_digest(source)
    assert recorder.paths == [source, source]


def test_file_digest_without_scope_always_reads_bytes(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    for _ in range(2):
        peri_scribe.sources.authentication.file_digest(source)
    assert recorder.paths == [source, source]


def test_scope_shares_nested_owner_and_restores_distinct_owner_after_failure(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.sources.authentication.scope(tmp_path):
        original = peri_scribe.sources.authentication.CURRENT.get()
        with peri_scribe.sources.authentication.scope(tmp_path / "."):
            assert peri_scribe.sources.authentication.CURRENT.get() is original
        message = "interrupted"
        with (
            pytest.raises(ValueError, match="interrupted"),
            peri_scribe.sources.authentication.scope(tmp_path / "other"),
        ):
            raise ValueError(message)
        assert peri_scribe.sources.authentication.CURRENT.get() is original
    assert peri_scribe.sources.authentication.CURRENT.get() is None
    assert original is not None
    assert not original.live()
    assert not original.values


def test_file_digest_rejects_expired_copied_context(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        peri_scribe.sources.authentication.file_digest(source)
        copied = contextvars.copy_context()
    copied.run(peri_scribe.sources.authentication.file_digest, source)
    assert recorder.paths == [source, source]


def test_scope_replaces_expired_context_instead_of_reviving_its_evidence(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.sources.authentication.scope(tmp_path):
        copied = contextvars.copy_context()
        original = peri_scribe.sources.authentication.CURRENT.get()
    manager = peri_scribe.sources.authentication.scope(tmp_path)
    copied.run(manager.__enter__)
    try:
        current = copied.run(peri_scribe.sources.authentication.CURRENT.get)
        assert current is not original
        assert current is not None
        assert current.live()
    finally:
        copied.run(manager.__exit__, None, None, None)


def test_file_digest_rejects_other_process_ownership(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    with peri_scribe.sources.authentication.scope(tmp_path):
        original = peri_scribe.sources.authentication.CURRENT.get()
        assert original is not None
        replaced = dataclasses.replace(original, process=os.getpid() + 1)
        token = peri_scribe.sources.authentication.CURRENT.set(replaced)
        try:
            assert not replaced.live()
            assert peri_scribe.sources.authentication.file_digest(source) == (
                hashlib.sha256(b"source").hexdigest()
            )
            assert not replaced.values
        finally:
            peri_scribe.sources.authentication.CURRENT.reset(token)


def test_file_digest_shares_admitted_concurrent_reads(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
    ):
        futures = [
            executor.submit(
                contextvars.copy_context().run,
                peri_scribe.sources.authentication.file_digest,
                source,
            )
            for _ in range(8)
        ]
        checksums = [future.result() for future in futures]
    assert checksums == [hashlib.sha256(b"source").hexdigest()] * len(futures)
    assert recorder.paths == [source]


def test_scope_is_bounded_by_standalone_preparation(tmp_path: pathlib.Path) -> None:
    with peri_scribe.preparation.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        assert owner.directory == tmp_path / "sources"
    assert owner is not None
    assert not owner.live()


def test_inventory_digest_defers_resolution_until_reuse(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        with unittest.mock.patch.object(pathlib.Path, "resolve") as resolve:
            first = peri_scribe.sources.authentication.inventory_digest(source)
        resolve.assert_not_called()
        assert owner.pending[source].checksum == first
        assert not owner.values
        assert peri_scribe.sources.authentication.file_digest(source) == first
        assert not owner.pending
        assert peri_scribe.sources.authentication.inventory_digest(source) == first
    assert recorder.paths == [source]
    assert not owner.pending


@pytest.mark.parametrize("change", ["same_timestamp", "replacement", "size"])
def test_inventory_digest_reauthenticates_changed_pending_inputs(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
    original = source.stat()
    with peri_scribe.sources.authentication.scope(tmp_path):
        first = peri_scribe.sources.authentication.inventory_digest(source)
        if change == "replacement":
            replacement = source.with_name("replacement")
            replacement.write_bytes(b"other")
            replacement.replace(source)
            os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        else:
            tests.helpers.factories.peri_scribe.sources.authentication.rewrite_with_changed_ctime(
                source,
                b"other" if change == "same_timestamp" else b"longer",
                timestamps=(original.st_atime_ns, original.st_mtime_ns),
            )
        if change == "same_timestamp":
            changed = source.stat()
            assert changed.st_dev == original.st_dev
            assert changed.st_ino == original.st_ino
            assert changed.st_size == original.st_size
            assert changed.st_mtime_ns == original.st_mtime_ns
            assert changed.st_ctime_ns != original.st_ctime_ns
        second = peri_scribe.sources.authentication.inventory_digest(source)
    assert first != second
    assert second == hashlib.sha256(source.read_bytes()).hexdigest()


def test_inventory_digest_rejects_changes_while_hashing(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"first")
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
            peri_scribe.sources.authentication.inventory_digest(source)
        assert not owner.pending
        assert not owner.values


@pytest.mark.parametrize("symlink", [False, True])
def test_inventory_digest_never_reuses_outside_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    symlink: bool,
) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"source")
    directory = tmp_path / "sources"
    directory.mkdir()
    source = directory / "link" if symlink else outside
    if symlink:
        source.symlink_to(outside)
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(directory):
        for authenticate in (
            peri_scribe.sources.authentication.inventory_digest,
            peri_scribe.sources.authentication.inventory_digest,
            peri_scribe.sources.authentication.file_digest,
        ):
            assert authenticate(source) == hashlib.sha256(b"source").hexdigest()
    assert recorder.paths == [source, source, source]


@pytest.mark.parametrize("outside", [False, True])
def test_file_digest_rechecks_parent_symlink_before_pending_admission(
    tmp_path: pathlib.Path,
    *,
    outside: bool,
) -> None:
    directory = tmp_path / "sources"
    first = directory / "first"
    second = tmp_path / "outside" if outside else directory / "second"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "snapshot").write_bytes(b"first")
    (second / "snapshot").write_bytes(b"other")
    parent = directory / "link"
    parent.symlink_to(first, target_is_directory=True)
    source = parent / "snapshot"
    with peri_scribe.sources.authentication.scope(directory):
        original = peri_scribe.sources.authentication.inventory_digest(source)
        parent.unlink()
        parent.symlink_to(second, target_is_directory=True)
        current = peri_scribe.sources.authentication.file_digest(source)
    assert original == hashlib.sha256(b"first").hexdigest()
    assert current == hashlib.sha256(b"other").hexdigest()


@pytest.mark.parametrize("inventory", [False, True])
def test_inventory_digest_expires_pending_evidence_in_copied_context(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    inventory: bool,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        peri_scribe.sources.authentication.inventory_digest(source)
        copied = contextvars.copy_context()
        owner = peri_scribe.sources.authentication.CURRENT.get()
    assert owner is not None
    assert not owner.pending
    authenticate = (
        peri_scribe.sources.authentication.inventory_digest
        if inventory
        else peri_scribe.sources.authentication.file_digest
    )
    assert copied.run(authenticate, source) == hashlib.sha256(b"source").hexdigest()
    assert recorder.paths == [source, source]


@pytest.mark.parametrize("inventory", [False, True])
def test_authentication_rejects_inherited_locked_owner_before_acquiring_lock(
    tmp_path: pathlib.Path,
    *,
    inventory: bool,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    authenticate = (
        peri_scribe.sources.authentication.inventory_digest
        if inventory
        else peri_scribe.sources.authentication.file_digest
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        original = peri_scribe.sources.authentication.CURRENT.get()
        assert original is not None
        inherited = dataclasses.replace(original, process=os.getpid() + 1)
        token = peri_scribe.sources.authentication.CURRENT.set(inherited)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                inherited.lock.acquire()
                try:
                    future = executor.submit(
                        contextvars.copy_context().run,
                        authenticate,
                        source,
                    )
                    assert (
                        future.result(timeout=5)
                        == hashlib.sha256(b"source").hexdigest()
                    )
                finally:
                    inherited.lock.release()
        finally:
            peri_scribe.sources.authentication.CURRENT.reset(token)


def test_inventory_digest_shares_concurrent_alternating_requests(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    with (
        peri_scribe.sources.authentication.scope(tmp_path),
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
    ):
        functions = (
            peri_scribe.sources.authentication.inventory_digest,
            peri_scribe.sources.authentication.file_digest,
        )
        futures = [
            executor.submit(
                contextvars.copy_context().run,
                functions[index % 2],
                source,
            )
            for index in range(8)
        ]
        checksums = [future.result() for future in futures]
    assert checksums == [hashlib.sha256(b"source").hexdigest()] * len(futures)
    assert recorder.paths == [source]


def test_inventory_digest_without_owner_reads_each_request(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    for _ in range(2):
        assert peri_scribe.sources.authentication.inventory_digest(source) == (
            hashlib.sha256(b"source").hexdigest()
        )
    assert recorder.paths == [source, source]


@pytest.mark.parametrize("inventory", [False, True])
def test_authentication_rechecks_owner_after_admission_lock(
    tmp_path: pathlib.Path,
    *,
    inventory: bool,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    authenticate = (
        peri_scribe.sources.authentication.inventory_digest
        if inventory
        else peri_scribe.sources.authentication.file_digest
    )
    with peri_scribe.sources.authentication.scope(tmp_path):
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        with unittest.mock.patch.object(
            peri_scribe.sources.authentication.Scope,
            "live",
            side_effect=[True, False],
        ):
            assert authenticate(source) == hashlib.sha256(b"source").hexdigest()
        assert not owner.pending
        assert not owner.values


def test_scope_cleanup_preserves_parent_evidence_in_different_process(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "snapshot"
    source.write_bytes(b"source")
    with contextlib.ExitStack() as scopes:
        scopes.enter_context(peri_scribe.sources.authentication.scope(tmp_path))
        owner = peri_scribe.sources.authentication.CURRENT.get()
        assert owner is not None
        peri_scribe.sources.authentication.inventory_digest(source)
        with unittest.mock.patch.object(
            peri_scribe.sources.authentication.os,
            "getpid",
            return_value=owner.process + 1,
        ):
            scopes.close()
            assert not owner.live()
    assert peri_scribe.sources.authentication.CURRENT.get() is None
    assert owner.pending
    owner.active.clear()
