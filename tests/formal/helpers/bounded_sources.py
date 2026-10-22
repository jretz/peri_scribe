"""Observe source lifetimes through real catalog, worker and publication calls."""

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import functools
import hashlib
import pathlib
import re
import sqlite3
import threading
import typing

import pytest
import shapely

import peri_scribe.execution
import peri_scribe.fires.bounded_sources
import peri_scribe.fires.files
import peri_scribe.fires.history
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.catalog
import peri_scribe.geo.database
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.perimeters.classification_data
import peri_scribe.sources.snapshots
import tests.formal.helpers.paths
import tests.formal.helpers.tlc
import tests.helpers.factories.peri_scribe.geo.catalog


type Value = tuple[
    str,
    int,
    int,
    frozenset[str],
    frozenset[str],
    frozenset[str],
    frozenset[str],
    bool,
    int,
]
BLOCKS = ("first", "second")


class BuildArguments(typing.TypedDict):
    """Preserve the exact worker signature while its timing is observed."""

    catalog: peri_scribe.geo.catalog.Catalog
    groups: peri_scribe.fires.sources.FireRecordGroups
    keys: dict[int, str]
    cached: dict[int, peri_scribe.fires.bounded_sources.Rows]
    classifications: dict[int, peri_scribe.models.FireClassification]
    boundaries: peri_scribe.perimeters.classification_data.Boundaries | None


def members(value: str) -> frozenset[str]:
    """Preserve every block identifier in an exported TLC set.

    Args:
        value: TLC's symbolic block set.

    Returns:
        Exactly its first/second members.
    """
    return frozenset(re.findall(r"first|second", value))


def contract(
    graph: tests.formal.helpers.tlc.Graph,
) -> tests.formal.helpers.paths.Contract[Value]:
    """Keep every model variable and permit no invisible lifecycle transitions.

    Args:
        graph: Freshly checked source-reader graph.

    Returns:
        Complete state and transition projections.
    """
    return tests.formal.helpers.paths.Contract(
        graph=graph,
        values={
            node: (
                state["phase"].strip('"'),
                int(state["revision"]),
                int(state["pinned"]),
                members(state["bad"]),
                members(state["checked"]),
                members(state["complete"]),
                members(state["running"]),
                state["published"] == "TRUE",
                int(state["validatedRevision"]),
            )
            for node, state in graph.states.items()
        },
        actions={
            edge: edge.action for edges in graph.outgoing.values() for edge in edges
        },
        internal=frozenset(),
    )


@dataclasses.dataclass(kw_only=True)
class Observer:
    """Match one execution over authenticated files and real workers."""

    year: pathlib.Path
    checked_contract: tests.formal.helpers.paths.Contract[Value]
    edit_at: str | None = None
    poison: str | None = None
    bad_blocks: tuple[str, ...] = ()
    first_finished: int = 0
    phase: str = "closed"
    pinned: int = 0
    bad: set[str] = dataclasses.field(default_factory=set)
    checked: set[str] = dataclasses.field(default_factory=set)
    complete: set[str] = dataclasses.field(default_factory=set)
    running: set[str] = dataclasses.field(default_factory=set)
    validated_revision: int = 2
    published: bool = False
    lock: threading.RLock = dataclasses.field(default_factory=threading.RLock)
    started: threading.Barrier = dataclasses.field(
        default_factory=lambda: threading.Barrier(2, timeout=10),
    )
    preferred_done: threading.Event = dataclasses.field(default_factory=threading.Event)
    source: pathlib.Path = dataclasses.field(init=False)
    database: pathlib.Path = dataclasses.field(init=False)
    original_bytes: bytes = dataclasses.field(init=False)
    rows: tuple[peri_scribe.geo.package.FireRowRecord, ...] = dataclasses.field(
        init=False,
    )
    connections: tuple[sqlite3.Connection, ...] = ()
    execution: tests.formal.helpers.paths.Path[Value] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Create two independent fires with real source authentication."""
        original = tests.helpers.factories.peri_scribe.geo.catalog.rows()
        self.rows = original[0], original[2]
        self.source = tests.helpers.factories.peri_scribe.geo.catalog.create(
            peri_scribe.sources.snapshots.sources_directory_path(self.year),
            self.rows,
        )
        self.database = peri_scribe.sources.snapshots.record_cache_database_path(
            self.source.parent.parent,
        )
        self.original_bytes = self.source.read_bytes()
        self.execution = self.checked_contract.start(self.value())

    def value(self) -> Value:
        """Read source identity and observations of actual lifecycle boundaries.

        Returns:
            Every model variable, including the source revision read from disk.
        """
        return (
            self.phase,
            int(self.source.read_bytes() != self.original_bytes),
            self.pinned,
            frozenset(self.bad),
            frozenset(self.checked),
            frozenset(self.complete),
            frozenset(self.running),
            self.published,
            self.validated_revision,
        )

    def event(self, action: str) -> None:
        """Require the next event to extend the same checked execution.

        Args:
            action: The model action actually reached by production code.
        """
        self.execution = self.execution.transition(action, self.value())

    def edit(self, boundary: str) -> None:
        """Mutate authoritative bytes at exactly one requested boundary.

        Args:
            boundary: The actual production boundary currently reached.
        """
        if self.edit_at != boundary:
            return
        self.source.write_bytes(self.original_bytes + b" changed revision")
        if boundary == "before_pin":
            with contextlib.closing(sqlite3.connect(self.database)) as connection:
                info = self.source.stat()
                connection.execute(
                    "UPDATE snapshots SET size = ?, mtime_ns = ?, checksum = ?",
                    (
                        info.st_size,
                        info.st_mtime_ns,
                        peri_scribe.geo.database.snapshot_checksum(self.source),
                    ),
                )
                connection.commit()
        self.event("Edit")

    def damage(self) -> None:
        """Corrupt stored metadata or payloads before any source lease opens."""
        for block in self.bad_blocks:
            position = BLOCKS.index(block)
            with contextlib.closing(sqlite3.connect(self.database)) as connection:
                if self.poison == "metadata":
                    connection.execute(
                        "UPDATE rows SET evidence_fingerprint = 'damaged' "
                        "WHERE rowid = ?",
                        (position + 1,),
                    )
                else:
                    kind = "attributes" if self.poison == "ownership" else "geometry"
                    identifier = connection.execute(
                        f"SELECT {kind}_id FROM rows ORDER BY rowid LIMIT 1 OFFSET ?",
                        (position,),
                    ).fetchone()[0]
                    table = (
                        "attribute_payloads"
                        if kind == "attributes"
                        else "geometry_payloads"
                    )
                    connection.execute(
                        f"UPDATE {table} SET value = ? WHERE id = ?",
                        (b"damaged", identifier),
                    )
                connection.commit()
            self.bad.add(block)
            self.event("Poison")

    def abort(self) -> None:
        """Record rejection only when a real production operation has raised."""
        if self.phase != "aborting":
            self.phase = "aborting"
            self.event("Abort")

    def closed_connections(self) -> None:
        """Ensure the real lease owner has closed all readers after workers settle."""
        assert not self.running
        for connection in self.connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Wrap real policy calls while controlling only timing and external evidence.

        Args:
            patch: Test-scoped restoration for boundary observers.
        """
        pin = peri_scribe.geo.catalog.pin_connections
        metadata = peri_scribe.geo.catalog.load_metadata

        def pinned(
            stack: contextlib.ExitStack,
            files: list[pathlib.Path],
        ) -> tuple[sqlite3.Connection, ...]:
            self.connections = pin(stack, files)
            self.pinned = self.value()[1]
            self.phase = "metadata"
            self.event("Pin")
            self.edit("pin")
            return self.connections

        @functools.wraps(metadata)
        def loaded(
            connections: tuple[sqlite3.Connection, ...],
            files: list[pathlib.Path],
            checksums: tuple[tuple[pathlib.Path, str], ...],
            directory: pathlib.Path,
        ) -> peri_scribe.geo.catalog.Catalog:
            try:
                result = metadata(connections, files, checksums, directory)
            except OSError, ValueError, sqlite3.Error:
                self.abort()
                raise
            assert all(
                row.record.geometry is None and row.attributes == {}
                for row in result.read.rows
            )
            assert result.read.source_checksums == (
                (
                    self.source,
                    peri_scribe.geo.database.snapshot_checksum(self.source)
                    if self.pinned == self.value()[1]
                    else hashlib.sha256(self.original_bytes).hexdigest(),
                ),
            )
            self.phase = "ownership"
            self.event("Metadata")
            self.edit("metadata")
            return result

        patch.setattr(peri_scribe.geo.catalog, "pin_connections", pinned)
        patch.setattr(peri_scribe.geo.catalog, "load_metadata", loaded)
        self.install_reads(patch)
        self.install_work(patch)
        self.install_release(patch)

    def install_reads(self, patch: pytest.MonkeyPatch) -> None:
        """Observe completed ownership and authenticated payload reads.

        Args:
            patch: Restoration owner for production call wrappers.
        """
        prepare = peri_scribe.fires.bounded_sources.prepare_groups
        hydrate = peri_scribe.geo.catalog.Catalog.hydrate

        def owned(
            catalog: peri_scribe.geo.catalog.Catalog,
        ) -> peri_scribe.fires.sources.FireRecordGroups:
            try:
                result = prepare(catalog)
            except OSError, ValueError, sqlite3.Error:
                self.abort()
                raise
            assert result.groups == ((0,), (1,))
            self.phase = "work"
            self.event("Ownership")
            self.edit("ownership")
            return result

        def hydrated(
            catalog: peri_scribe.geo.catalog.Catalog,
            positions: collections.abc.Sequence[int],
        ) -> peri_scribe.fires.sources.ReadFireSources:
            result = hydrate(catalog, positions)
            assert result.rows == tuple(self.rows[position] for position in positions)
            with self.lock:
                if self.phase == "work":
                    self.checked.add(BLOCKS[positions[0]])
                    self.event("Verify")
            return result

        patch.setattr(peri_scribe.fires.bounded_sources, "prepare_groups", owned)
        patch.setattr(peri_scribe.geo.catalog.Catalog, "hydrate", hydrated)

    def completed(
        self,
        block: str,
        result: peri_scribe.fires.bounded_sources.CompletedFire,
    ) -> None:
        """Record completed output only while the invocation still accepts results.

        Args:
            block: The worker whose real computation just returned.
            result: Actual rows returned by production reconciliation.
        """
        with self.lock:
            self.running.remove(block)
            if self.phase == "aborting":
                self.event("Settle")
            else:
                assert (
                    result.rows.perimeters
                    or result.rows.points
                    or result.rows.incidents
                )
                self.complete.add(block)
                self.event("Finish")

    def install_work(self, patch: pytest.MonkeyPatch) -> None:
        """Control two real workers' overlap and inspect their actual returned rows.

        Args:
            patch: Restoration owner for the worker wrapper.
        """
        build = peri_scribe.fires.bounded_sources.build_fire

        @functools.wraps(build)
        def built(
            position: int,
            **kwargs: typing.Unpack[BuildArguments],
        ) -> peri_scribe.fires.bounded_sources.CompletedFire:
            block = BLOCKS[position]
            with self.lock:
                self.running.add(block)
                self.event("Admit")
            self.started.wait()
            if position != self.first_finished:
                assert self.preferred_done.wait(10)
            with self.lock:
                if position == self.first_finished:
                    self.edit("work")
                for connection in self.connections:
                    connection.execute("SELECT 1")
            try:
                result = build(position, **kwargs)
            except OSError, ValueError, sqlite3.Error:
                with self.lock:
                    self.abort()
                    self.running.remove(block)
                    self.event("Settle")
                raise
            else:
                self.completed(block, result)
                return result
            finally:
                if position == self.first_finished:
                    self.preferred_done.set()

        patch.setattr(peri_scribe.fires.bounded_sources, "build_fire", built)
        patch.setattr(peri_scribe.fires.history, "HISTORY_ROW_WORKER_COUNT", 2)
        boundaries = peri_scribe.perimeters.classification_data.Boundaries(
            box=shapely.box(-1, -1, 1, 1),
            border=shapely.LineString([(1, -1), (1, 1)]),
        )
        patch.setattr(
            peri_scribe.fires.bounded_sources,
            "load_boundaries",
            lambda _year: boundaries,
        )

    def install_release(self, patch: pytest.MonkeyPatch) -> None:
        """Observe final source validation, actual connection closure and publication.

        Args:
            patch: Restoration owner for lifecycle wrappers.
        """
        verify = peri_scribe.geo.catalog.Catalog.verify
        opened = peri_scribe.geo.catalog.open_catalog
        publish = peri_scribe.fires.files.publish_full_rows

        def validated(catalog: peri_scribe.geo.catalog.Catalog) -> None:
            try:
                verify(catalog)
            except OSError:
                self.abort()
                raise
            self.validated_revision = self.pinned
            self.phase = "validated"
            self.event("Validate")
            self.edit("validated")

        @contextlib.contextmanager
        def leased(
            directory: pathlib.Path,
        ) -> collections.abc.Generator[peri_scribe.geo.catalog.Catalog]:
            with opened(directory) as catalog:
                yield catalog
            self.closed_connections()
            self.phase = "released"
            self.event("Release")
            self.edit("released")

        @functools.wraps(publish)
        def published(
            output_path: pathlib.Path,
            perimeter_rows: list[dict[str, object]],
            point_rows: list[dict[str, object]],
            incident_rows: list[dict[str, object]],
            *,
            generation: str | None,
        ) -> pathlib.Path:
            self.closed_connections()
            result = publish(
                output_path,
                perimeter_rows,
                point_rows,
                incident_rows,
                generation=generation,
            )
            signature = peri_scribe.fires.reuse.validated_signature(
                result,
                peri_scribe.fires.files.FULL_LAYER_NAMES,
            )
            assert result.is_file()
            assert signature is not None
            self.published = True
            self.phase = "published"
            self.event("Publish")
            self.edit("published")
            return result

        patch.setattr(peri_scribe.geo.catalog.Catalog, "verify", validated)
        patch.setattr(peri_scribe.geo.catalog, "open_catalog", leased)
        patch.setattr(peri_scribe.fires.files, "publish_full_rows", published)

    def run(self) -> None:
        """Execute the bounded stage, including its real success or refusal outcome."""
        self.damage()
        self.edit("before_pin")
        with pytest.MonkeyPatch.context() as patch, peri_scribe.execution.sharing():
            self.install(patch)
            try:
                result = peri_scribe.fires.files.write_bounded_full_geography(
                    self.year,
                    generation="bounded-source-generation",
                    unconditional=True,
                )
            except OSError:
                assert self.edit_at in {"pin", "metadata", "ownership", "work"}
                result = None
            if result is None:
                self.closed_connections()
                assert self.phase == "aborting"
                self.phase = "fallback"
                self.event("Fallback")
                assert not peri_scribe.fires.files.history_geopackage_path(
                    self.year,
                ).exists()
            else:
                assert self.phase == "published"
                assert not self.bad
