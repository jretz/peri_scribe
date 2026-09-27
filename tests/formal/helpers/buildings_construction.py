"""Replay construction with real workers, partitions, SQLite, and replacement."""

from __future__ import annotations

import asyncio
import collections
import collections.abc
import dataclasses
import pathlib
import re
import sqlite3
import threading
import typing

import numpy as np
import pytest

import peri_scribe.exceptions
import peri_scribe.sources.buildings
import peri_scribe.sources.catalog
import spatial_data.point_store
import tests.helpers.factories.spatial_data.point_store


MODELED_LIMIT = 2
MODELED_WORKERS = {1, 2, 3}


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Fault/initial-output parameters read directly from the checked TLC graph."""

    previous: str
    fault: str
    bad_worker: int
    partial: bool


def cases(states: list[dict[str, str]]) -> list[Case]:
    """Project unique model scenarios, retaining every archive failure position.

    Args:
        states: All reachable TLC states.

    Returns:
        Deterministically ordered scenarios for real execution.
    """
    return sorted(
        {
            Case(
                previous=state["previous"].strip('"'),
                fault=state["fault"].strip('"'),
                bad_worker=int(state["badWorker"]),
                partial=state["fault"] == '"archive"'
                and int(state["badWorker"]) in members(state["appended"]),
            )
            for state in states
            if state["temporary"] == "FALSE"
            and (state["badWorker"] == "1" or state["fault"] == '"archive"')
        },
        key=lambda case: (case.previous, case.fault, case.bad_worker, case.partial),
    )


def members(value: str) -> set[int]:
    """Decode a TLC finite worker set.

    Args:
        value: The TLC set representation.

    Returns:
        Worker identifiers.
    """
    return {int(item) for item in re.findall(r"\d+", value)}


@dataclasses.dataclass(frozen=True, kw_only=True)
class Workers:
    """Mutable event collections record a controlled real thread schedule."""

    case: Case
    ready: threading.Event = dataclasses.field(default_factory=threading.Event)
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    started: set[int] = dataclasses.field(default_factory=set)
    active: set[int] = dataclasses.field(default_factory=set)
    appended: set[int] = dataclasses.field(default_factory=set)
    finished: set[int] = dataclasses.field(default_factory=set)
    cancelled: set[int] = dataclasses.field(default_factory=set)
    maximum_active: list[int] = dataclasses.field(default_factory=list)
    phases: list[str] = dataclasses.field(default_factory=list)
    directories: list[pathlib.Path] = dataclasses.field(default_factory=list)

    def stream(
        self,
        url: str,
        files: spatial_data.point_store.PartitionFiles,
        *,
        stopped: threading.Event,
    ) -> int:
        """Hold an in-flight append across cancellation to test staging lifetime.

        Args:
            url: Synthetic worker number in the download URL.
            files: Real shared partition writer.
            stopped: Real cancellation signal owned by run_blocking.

        Returns:
            Number of point records appended.

        Raises:
            ExternalDataError: The configured archive failure.
        """
        identifier = int(url.rsplit("/", maxsplit=1)[1])
        with self.lock:
            self.started.add(identifier)
            self.active.add(identifier)
            self.maximum_active.append(len(self.active))
            self.directories.append(files.directory)
            if {1, 2} <= self.started:
                self.ready.set()
        try:
            if identifier in {1, 2}:
                assert self.ready.wait(timeout=5), "Workers did not overlap"
            if (
                self.case.fault == "archive"
                and identifier == self.case.bad_worker
                and not self.case.partial
            ):
                message = "Injected archive conversion failure"
                raise peri_scribe.exceptions.ExternalDataError(message)
            stopping = self.case.fault == "cancel" or (
                self.case.fault == "archive"
                and self.case.bad_worker in {1, 2}
                and identifier != self.case.bad_worker
            )
            if stopping:
                assert stopped.wait(timeout=5), "Task group did not stop its sibling"
                with self.lock:
                    self.cancelled.add(identifier)
            assert files.directory.is_dir(), "Staging removed before the worker exited"
            spatial_data.point_store.append_centroids_to_partitions(
                np.asarray([[identifier / 10, 0]], dtype=float),
                files,
            )
            with self.lock:
                self.appended.add(identifier)
            if self.case.fault == "archive" and identifier == self.case.bad_worker:
                message = "Injected archive failure after partial conversion"
                raise peri_scribe.exceptions.ExternalDataError(message)
            with self.lock:
                self.finished.add(identifier)
            return 1
        finally:
            with self.lock:
                self.active.remove(identifier)

    def quiescent(self, phase: str) -> None:
        """Record a build/validation/publication boundary after every worker exits.

        Args:
            phase: The corresponding TLA phase.
        """
        assert not self.active
        assert self.finished == {1, 2, 3}
        self.phases.append(phase)


async def cancel_collection(
    original: collections.abc.Callable[
        [typing.Iterable[str], spatial_data.point_store.PartitionFiles],
        collections.abc.Coroutine[typing.Any, typing.Any, None],
    ],
    workers: Workers,
    urls: typing.Iterable[str],
    files: spatial_data.point_store.PartitionFiles,
) -> None:
    """Cancel the real collection task once two blocking workers have started.

    Args:
        original: The production task group implementation.
        workers: Thread schedule observations.
        urls: The three synthetic archive URLs.
        files: Real staging partitions.
    """
    task = asyncio.create_task(original(urls, files))
    assert await asyncio.to_thread(workers.ready.wait, 5)
    task.cancel()
    await task


def install_boundaries(
    workers: Workers,
    output: pathlib.Path,
    patch: pytest.MonkeyPatch,
) -> None:
    """Instrument real operations at modeled boundaries.

    Args:
        workers: Controlled worker schedule and phase observations.
        output: Final published output path.
        patch: Scoped replacement owner.
    """
    original_build = spatial_data.point_store.build_tiles_database
    original_validate = spatial_data.point_store.is_valid_database
    original_replace = pathlib.Path.replace
    original_stream = peri_scribe.sources.buildings.stream_state_archives

    def build(partitions: pathlib.Path, path: pathlib.Path) -> int:
        """Run a real build with an optional subsequent failure.

        Args:
            partitions: Real partition inputs.
            path: Staged database path.

        Returns:
            The real build's point count.

        Raises:
            OSError: Configured failure after staging writes.
        """
        workers.quiescent("build")
        count = original_build(partitions, path)
        if workers.case.fault == "build":
            message = "Injected database build failure after staging writes"
            raise OSError(message)
        return count

    def validate(path: pathlib.Path) -> bool:
        """Keep the initial cache check real and fault staged validation.

        Args:
            path: Existing or staged database.

        Returns:
            The real validation result unless a staged failure is injected.
        """
        if path != output:
            workers.quiescent("validate")
            if workers.case.fault == "validate":
                return False
        return original_validate(path)

    def replace(path: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """Observe atomic replacement or fail before changing the destination.

        Args:
            path: Fully built staged database.
            target: Published database path.

        Returns:
            The real replacement destination.

        Raises:
            OSError: The configured replacement failure.
        """
        workers.quiescent("publish")
        if workers.case.fault == "publish":
            message = "Injected replacement failure"
            raise OSError(message)
        return original_replace(path, target)

    patch.setattr(peri_scribe.sources.buildings, "ARCHIVE_CONCURRENCY", 2)
    patch.setattr(
        peri_scribe.sources.buildings,
        "stream_state_archive",
        workers.stream,
    )
    patch.setattr(spatial_data.point_store, "build_tiles_database", build)
    patch.setattr(spatial_data.point_store, "is_valid_database", validate)
    patch.setattr(pathlib.Path, "replace", replace)
    if workers.case.fault == "cancel":
        patch.setattr(
            peri_scribe.sources.buildings,
            "stream_state_archives",
            lambda urls, files: cancel_collection(
                original_stream,
                workers,
                urls,
                files,
            ),
        )


def replay(case: Case, states: list[dict[str, str]], directory: pathlib.Path) -> None:
    """Check real terminal state and boundary observations against reachable TLC states.

    Args:
        case: A checked construction scenario.
        states: TLC state output, used as the expected protocol behavior.
        directory: Isolated data root.
    """
    output = directory / "sources" / "buildings.sqlite"
    output.parent.mkdir(parents=True)
    if case.previous == "valid":
        tests.helpers.factories.spatial_data.point_store.write_database(
            np.asarray([[4.2, 0]], dtype=float),
            output,
        )
    elif case.previous == "invalid":
        output.write_bytes(b"existing invalid database retained on failure")
    previous = output.read_bytes() if output.exists() else None
    workers = Workers(case=case)
    source = dataclasses.replace(
        peri_scribe.sources.catalog.BUILDINGS_SOURCE,
        states=("1", "2", "3"),
        state_urls=None,
        url="https://example.test/{state}",
    )
    failed = False
    with pytest.MonkeyPatch.context() as patch:
        install_boundaries(workers, output, patch)
        try:
            result = peri_scribe.sources.buildings.fetch_buildings_database(
                source,
                directory,
            )
        except (
            peri_scribe.exceptions.ExternalDataError,
            OSError,
            asyncio.CancelledError,
        ):
            failed = True
        else:
            assert result == (output,)
    check_outcome(workers, states, output, previous, failed=failed)


def check_outcome(
    workers: Workers,
    states: list[dict[str, str]],
    output: pathlib.Path,
    previous: bytes | None,
    *,
    failed: bool,
) -> None:
    """Compare actual cleanup and durable data with checked terminal states.

    Args:
        workers: The completed execution observations.
        states: Model states supplying allowed outcomes.
        output: Final output path.
        previous: Preexisting output bytes, if any.
        failed: Whether the real caller received a failure.
    """
    case = workers.case
    assert not workers.active
    assert all(not path.exists() for path in workers.directories)
    assert max(workers.maximum_active, default=0) <= MODELED_LIMIT
    assert sorted(path.name for path in output.parent.iterdir()) == (
        [output.name] if output.exists() else []
    )
    phase = "cached" if case.previous == "valid" else "failed" if failed else "done"
    matching = [
        state
        for state in states
        if state["previous"] == f'"{case.previous}"'
        and state["fault"] == f'"{case.fault}"'
        and state["badWorker"] == str(case.bad_worker)
    ]
    terminal = [
        state
        for state in matching
        if state["phase"] == f'"{phase}"'
        and state["temporary"] == "FALSE"
        and members(state["appended"]) == workers.appended
        and re.findall(r'"([a-z]+)"', state["phases"]) == workers.phases
        and re.findall(r'"([a-z]+)"', state["worker"]) == worker_outcomes(workers)
    ]
    assert terminal, (case, phase, workers.appended)
    for boundary in workers.phases:
        assert any(state["phase"] == f'"{boundary}"' for state in matching)
    expected_outputs = {state["output"].strip('"') for state in terminal}
    assert len(expected_outputs) == 1
    if expected_outputs == {"new"}:
        assert spatial_data.point_store.is_valid_database(output)
        with sqlite3.connect(output) as connection:
            rows = connection.execute(
                "SELECT building_count, payload FROM tiles",
            ).fetchall()
        assert sum(count for count, _ in rows) == len(MODELED_WORKERS)
        assert collections.Counter(
            tuple(point)
            for _, payload in rows
            for point in spatial_data.point_store.decode_payload(payload).tolist()
        ) == collections.Counter({(10_000, 0): 1, (20_000, 0): 1, (30_000, 0): 1})
    else:
        assert (output.read_bytes() if output.exists() else None) == previous
    if case.previous != "valid" and case.fault in {"archive", "cancel"}:
        assert not workers.phases
        if case.fault == "cancel" or case.bad_worker in {1, 2}:
            assert workers.cancelled
            assert {1, 2} <= workers.started


def worker_outcomes(workers: Workers) -> list[str]:
    """Project actual completed worker observations onto the model's terminal states.

    Args:
        workers: The completed execution's cancellation and append observations.

    Returns:
        One terminal state per modeled worker in numeric order.
    """
    if workers.case.previous == "valid":
        return ["waiting"] * len(MODELED_WORKERS)
    return [
        "failed"
        if workers.case.fault == "archive" and worker == workers.case.bad_worker
        else "cancelled"
        if worker in workers.cancelled or worker not in workers.started
        else "done"
        for worker in sorted(MODELED_WORKERS)
    ]
