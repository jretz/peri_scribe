"""Share byte authentication only while a live preparation owns stable source inputs.

Design and verification:
[Source-index preparation](../../../docs/algorithms/source-index-preparation.md).
"""

from __future__ import annotations

import collections.abc
import concurrent.futures
import contextlib
import contextvars
import dataclasses
import hashlib
import os
import pathlib
import threading


type Stamp = tuple[int, int, int, int, int]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Evidence:
    """Bind exact source bytes to the complete observed filesystem identity."""

    stamp: Stamp
    checksum: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scope:
    """Keep borrowed authentication invalid after cleanup or process replacement."""

    directory: pathlib.Path
    process: int
    active: threading.Event
    values: dict[pathlib.Path, Evidence] = dataclasses.field(default_factory=dict)
    pending: dict[pathlib.Path, Evidence] = dataclasses.field(default_factory=dict)
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def live(self) -> bool:
        """Reject expired copied contexts and state inherited by a forked process.

        Returns:
            Whether this process still owns the scope's stable inputs.
        """
        return self.active.is_set() and self.process == os.getpid()


CURRENT: contextvars.ContextVar[Scope | None] = contextvars.ContextVar(
    "source_authentication",
    default=None,
)


@contextlib.contextmanager
def scope(directory: pathlib.Path) -> collections.abc.Generator[None]:
    """Reuse nested preparation without lending evidence to another invocation.

    Args:
        directory: Source directory whose inputs remain owned for this scope.

    Yields:
        Control with execution-local checksum sharing available.
    """
    resolved = directory.resolve()
    existing = CURRENT.get()
    if existing is not None and existing.live() and existing.directory == resolved:
        yield
        return
    active = threading.Event()
    active.set()
    owner = Scope(directory=resolved, process=os.getpid(), active=active)
    token = CURRENT.set(owner)
    try:
        yield
    finally:
        if owner.process == os.getpid():
            with owner.lock:
                active.clear()
                owner.values.clear()
                owner.pending.clear()
        CURRENT.reset(token)


def file_stamp(path: pathlib.Path) -> Stamp:
    """Include change time so restoring modification time cannot preserve evidence.

    Args:
        path: Source file whose complete filesystem identity is observed.

    Returns:
        Device, inode, size, modification time and change time.
    """
    status = path.stat()
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def read_file_digest(path: pathlib.Path) -> str:
    """Authenticate complete bytes without retaining a second file-sized buffer.

    Args:
        path: File whose current bytes need a SHA-256 identity.

    Returns:
        The SHA-256 checksum.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_file_evidence(path: pathlib.Path) -> Evidence:
    """Reject a read whose full filesystem identity changes while hashing.

    Args:
        path: File whose complete current bytes are authenticated.

    Returns:
        Fresh bytes bound to matching stamps before and after the read.

    Raises:
        OSError: If the file changes during authentication or cannot be read.
    """
    stamp = file_stamp(path)
    checksum = read_file_digest(path)
    if file_stamp(path) != stamp:
        message = f"Source changed while authenticating {path}"
        raise OSError(message)
    return Evidence(stamp=stamp, checksum=checksum)


def read_inventory_batch(
    paths: collections.abc.Sequence[pathlib.Path],
    cancelled: threading.Event,
) -> dict[pathlib.Path, Evidence]:
    """Keep a worker's complete byte reads local until its caller joins all work.

    Args:
        paths: Independent strided portion of an inventory.
        cancelled: Stop remaining reads after another worker or the caller fails.

    Returns:
        Fresh evidence without accessing an owning context or shared dictionary.

    Raises:
        concurrent.futures.CancelledError: If cancellation precedes a file read.
    """
    result = {}
    for path in paths:
        if cancelled.is_set():
            raise concurrent.futures.CancelledError
        result[path] = read_file_evidence(path)
    return result


def read_inventory_evidence(
    paths: collections.abc.Sequence[pathlib.Path],
) -> dict[pathlib.Path, Evidence]:
    """Bound independent reads and join every worker before returning or failing.

    Args:
        paths: Previously unseen absolute inventory paths.

    Returns:
        Completed fresh evidence for every input path.
    """
    cancelled = threading.Event()
    workers = min(4, os.cpu_count() or 1, len(paths))
    if workers <= 1:
        return read_inventory_batch(paths, cancelled)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures: list[concurrent.futures.Future[dict[pathlib.Path, Evidence]]] = []
    result = {}
    try:
        futures.extend(
            executor.submit(
                isolated_inventory_batch,
                paths[index::workers],
                cancelled,
            )
            for index in range(workers)
        )
        for future in concurrent.futures.as_completed(futures):
            result.update(future.result())
    except BaseException:
        cancelled.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return result


def isolated_inventory_batch(
    paths: collections.abc.Sequence[pathlib.Path],
    cancelled: threading.Event,
) -> dict[pathlib.Path, Evidence]:
    """Give each worker an empty context even on Python builds inheriting threads.

    Args:
        paths: Independent strided portion of an inventory.
        cancelled: Signal stopping remaining reads after an earlier failure.

    Returns:
        Completed evidence produced without a borrowed owning context.
    """
    return contextvars.Context().run(read_inventory_batch, paths, cancelled)


def publish_inventory_evidence(
    owner: Scope,
    evidence: collections.abc.Mapping[pathlib.Path, Evidence],
) -> None:
    """Publish a complete joined batch only while all captured inputs still match.

    Args:
        owner: The process and scope that requested the fresh reads.
        evidence: Completed worker results, with every worker already joined.

    Raises:
        OSError: If ownership expires or any source changes before admission.
    """
    message = "Source authentication scope expired before admission"
    if not owner.live():
        raise OSError(message)
    with owner.lock:
        if not owner.live():
            raise OSError(message)
        for path, value in evidence.items():
            if file_stamp(path) != value.stamp:
                message = f"Source changed while authenticating {path}"
                raise OSError(message)
        owner.pending.update(evidence)


def file_digest(path: pathlib.Path) -> str:
    """Read bytes freshly unless this live source scope already authenticated them.

    Args:
        path: File whose current content identity is requested.

    Returns:
        A fresh or scope-owned checksum for the current file identity.
    """
    owner = CURRENT.get()
    if owner is None or not owner.live():
        return read_file_digest(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(owner.directory):
        return read_file_digest(path)
    with owner.lock:
        if not owner.live():
            return read_file_digest(path)
        stamp = file_stamp(resolved)
        previous = owner.values.get(resolved)
        if previous is not None and previous.stamp == stamp:
            return previous.checksum
        pending = owner.pending.get(path.absolute())
        if pending is not None and pending.stamp == stamp:
            owner.values[resolved] = pending
            del owner.pending[path.absolute()]
            return pending.checksum
        value = read_file_evidence(resolved)
        owner.values[resolved] = value
        return value.checksum


def inventory_digest(path: pathlib.Path) -> str:
    """Defer canonical admission when the inventory first authenticates source bytes.

    Pending evidence can be borrowed only through ordinary authentication, which
    resolves the current path inside the source root and checks its complete stamp.

    Args:
        path: Inventory file whose current bytes need a source identity.

    Returns:
        A fresh checksum or evidence admitted by the live owning source scope.
    """
    owner = CURRENT.get()
    if owner is None or not owner.live():
        return read_file_digest(path)
    absolute = path.absolute()
    with owner.lock:
        if not owner.live():
            return read_file_digest(path)
        repeated = absolute in owner.pending or absolute in owner.values
        if not repeated:
            value = read_file_evidence(absolute)
            owner.pending[absolute] = value
            return value.checksum
    return file_digest(absolute)


def inventory_digests(
    paths: collections.abc.Sequence[pathlib.Path],
) -> tuple[str, ...]:
    """Authenticate ordered inventory occurrences with bounded fresh byte reads.

    Args:
        paths: Inventory paths in their source-generation order, including duplicates.

    Returns:
        Ordered SHA-256 values with ordinary canonical admission on repeated requests.

    Raises:
        OSError: If ownership expires before fresh evidence admission.
    """
    owner = CURRENT.get()
    if len(paths) <= 1 or owner is None or not owner.live():
        return tuple(inventory_digest(path) for path in paths)
    absolute = tuple(path.absolute() for path in paths)
    with owner.lock:
        if not owner.live():
            message = "Source authentication scope expired before admission"
            raise OSError(message)
        fresh = tuple(
            dict.fromkeys(
                path
                for path in absolute
                if path not in owner.pending and path not in owner.values
            ),
        )
    if not fresh:
        return tuple(inventory_digest(path) for path in absolute)
    evidence = read_inventory_evidence(fresh)
    publish_inventory_evidence(owner, evidence)
    remaining = set(evidence)
    result = []
    for path in absolute:
        if path in remaining:
            result.append(evidence[path].checksum)
            remaining.remove(path)
        else:
            result.append(inventory_digest(path))
    return tuple(result)
