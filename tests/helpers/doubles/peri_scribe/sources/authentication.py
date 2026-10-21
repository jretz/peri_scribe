"""Observe real byte hashing and inject a source change at the checksum boundary."""

from __future__ import annotations

import collections.abc
import concurrent.futures
import dataclasses
import pathlib
import threading

import peri_scribe.sources.authentication


@dataclasses.dataclass(frozen=True, kw_only=True)
class DigestRecorder:
    """Count complete real source reads independently of cache implementation."""

    read: collections.abc.Callable[[pathlib.Path], str]
    paths: list[pathlib.Path] = dataclasses.field(default_factory=list)
    replacement: bytes | None = None

    def __call__(self, path: pathlib.Path) -> str:
        """Read real bytes and optionally change them before identity revalidation.

        Args:
            path: The authenticated temporary source.

        Returns:
            The checksum of the bytes present before optional replacement.
        """
        self.paths.append(path)
        result = self.read(path)
        if self.replacement is not None:
            path.write_bytes(self.replacement)
        return result


@dataclasses.dataclass(frozen=True, kw_only=True)
class ControlledReader:
    """Hold one real read while another fails, retaining observed worker contexts."""

    read: collections.abc.Callable[[pathlib.Path], str]
    blocked: pathlib.Path | None = None
    failing: pathlib.Path | None = None
    entered: threading.Event = dataclasses.field(default_factory=threading.Event)
    released: threading.Event = dataclasses.field(default_factory=threading.Event)
    failed: threading.Event = dataclasses.field(default_factory=threading.Event)
    finished: list[pathlib.Path] = dataclasses.field(default_factory=list)
    owners: list[peri_scribe.sources.authentication.Scope | None] = dataclasses.field(
        default_factory=list,
    )

    def __call__(self, path: pathlib.Path) -> str:
        """Read actual bytes unless a controlled failure occurs before the read.

        Args:
            path: Temporary source observed by a worker.

        Returns:
            Its actual SHA-256 after an optional release barrier.

        Raises:
            OSError: For the selected failing source.
        """
        self.owners.append(peri_scribe.sources.authentication.CURRENT.get())
        if path == self.blocked:
            self.entered.set()
            assert self.released.wait(timeout=5)
        if path == self.failing:
            assert self.entered.wait(timeout=5)
            self.failed.set()
            message = "controlled source failure"
            raise OSError(message)
        result = self.read(path)
        self.finished.append(path)
        return result

    def interrupt(
        self,
        futures: collections.abc.Iterable[
            concurrent.futures.Future[
                dict[pathlib.Path, peri_scribe.sources.authentication.Evidence]
            ]
        ],
    ) -> collections.abc.Iterator[
        concurrent.futures.Future[
            dict[pathlib.Path, peri_scribe.sources.authentication.Evidence]
        ]
    ]:
        """Interrupt the caller only after its worker has entered a real byte read.

        Args:
            futures: Submitted work whose shutdown must finish before propagation.

        Raises:
            KeyboardInterrupt: Once the blocked worker has started.
        """
        assert tuple(futures)
        assert self.entered.wait(timeout=5)
        message = "controlled caller interruption"
        raise KeyboardInterrupt(message)
