"""Give one formal invocation temporary evidence shared by all of its child tools."""

import collections.abc
import contextlib
import fcntl
import functools
import hashlib
import json
import os
import pathlib
import tempfile


VARIABLE = "PERI_SCRIBE_FORMAL_CORPUS"
FORMAL_DIRECTORY = pathlib.Path(__file__).resolve().parents[1]


@functools.cache
def digest_file(path: pathlib.Path, modified: int, size: int) -> bytes:
    """Repeated consumers avoid rehashing files whose recorded metadata is unchanged.

    Args:
        path: One specification, adapter, or checker archive.
        modified: Nanosecond modification time belonging to this cache entry.
        size: Byte count belonging to this cache entry.

    Returns:
        The content checksum qualified by the same file metadata.
    """
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256")
    digest.update(f"{modified}:{size}".encode())
    return digest.digest()


def identity() -> str:
    """Inherited evidence remains valid only for the same specifications and checker.

    Returns:
        A content identity excluding deliberately mutated application source.
    """
    digest = hashlib.sha256()
    paths = sorted((FORMAL_DIRECTORY / "tla").glob("*.tla"))
    paths.extend(sorted((FORMAL_DIRECTORY / "tla").glob("*.cfg")))
    paths.extend(
        [
            FORMAL_DIRECTORY / "tla" / "models.toml",
            pathlib.Path(__file__),
            pathlib.Path(__file__).with_name("tlc.py"),
            pathlib.Path(__file__).with_name("corpus.py"),
        ],
    )
    jar = os.environ.get("PERI_SCRIBE_TLA_JAR")
    if jar:
        paths.append(pathlib.Path(jar))
    for path in paths:
        digest.update(path.name.encode())
        metadata = path.stat()
        digest.update(digest_file(path, metadata.st_mtime_ns, metadata.st_size))
    return digest.hexdigest()


def directory() -> pathlib.Path | None:
    """Reject stale model evidence inherited through an unrelated invocation.

    Returns:
        The active invocation's checked storage, or None outside such an invocation.

    Raises:
        RuntimeError: If inherited storage is absent or belongs to different inputs.
    """
    value = os.environ.get(VARIABLE)
    if value is None:
        return None
    path = pathlib.Path(value)
    marker = path / "session.json"
    lease = path / "owner.lock"
    if not marker.is_file() or not lease.is_file():
        message = "Formal corpus belongs to different specifications or an expired run"
        raise RuntimeError(message)
    with lease.open("rb") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            message = "Formal corpus owner has exited"
            raise RuntimeError(message)
    if json.loads(marker.read_text()) != identity():
        message = "Formal corpus belongs to different specifications or an expired run"
        raise RuntimeError(message)
    return path


@contextlib.contextmanager
def scope(path: pathlib.Path) -> collections.abc.Generator[pathlib.Path]:
    """Only a completed run can remove the evidence still needed by its children.

    Args:
        path: Fresh invocation-specific temporary storage.

    Yields:
        The evidence directory inherited by every child process.
    """
    path.mkdir(parents=True, exist_ok=True)
    with (path / "owner.lock").open("a+b") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (path / "session.json").write_text(json.dumps(identity()))
        previous = os.environ.get(VARIABLE)
        os.environ[VARIABLE] = str(path.resolve())
        try:
            yield path
        finally:
            (path / "session.json").unlink(missing_ok=True)
            if previous is None:
                os.environ.pop(VARIABLE, None)
            else:
                os.environ[VARIABLE] = previous


@contextlib.contextmanager
def temporary() -> collections.abc.Generator[pathlib.Path]:
    """Every top-level run starts with fresh evidence regardless of inherited settings.

    Yields:
        One run's storage, deleted only after its child tools have finished.
    """
    with (
        tempfile.TemporaryDirectory(prefix="peri-scribe-formal-") as value,
        scope(pathlib.Path(value)) as path,
    ):
        yield path
