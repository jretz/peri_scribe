"""Publish complete TLC graphs with shared immutable field values."""

import asyncio
import base64
import dataclasses
import pathlib
import tempfile
import typing

import tests.formal.helpers.tlc
import tests.formal.helpers.tlc_frame_wire
import tests.formal.helpers.tlc_worker


SAFETY_EXPORTS = {
    ("BoundarySpill", "BoundarySpill"): "STATES",
    ("CacheRead", "CacheRead"): "STATES",
    ("FeedCache", "FeedCache"): "STATES",
    ("GeographyPublication", "GeographyPublication"): "GRAPH",
    ("GeographyReaders", "GeographyReaders"): "GRAPH",
    ("GroupingForest", "GroupingForest"): "GRAPH",
    ("MonitorBackwardContext", "MonitorBackwardContext"): "STATES",
    ("MonitorProjection", "MonitorProjection"): "STATES",
    ("MonitorReader", "MonitorReader"): "STATES",
    ("MonitorSession", "MonitorSession"): "GRAPH",
    ("MonitorTasks", "MonitorTasks"): "GRAPH",
    ("NormalizedCache", "NormalizedCache"): "STATES",
    ("ParallelSourceAuthentication", "ParallelSourceAuthentication"): "GRAPH",
    ("ParsedCacheCompaction", "ParsedCacheCompaction"): "GRAPH",
    ("RunScheduler", "RunScheduler"): "COUNTS",
    ("SnapshotCollection", "SnapshotCollection"): "STATES",
    ("SourceWriters", "SourceWriters"): "STATES",
}

EXPORTS = SAFETY_EXPORTS | {
    ("BuildingsConstruction", "BuildingsConstruction"): "STATES",
    ("FeedCoordinator", "FeedCoordinator"): "STATES",
    ("FetchCrash", "FetchCrash"): "GRAPH",
    ("GeographyPublication", "GeographyPublicationLiveness"): "COUNTS",
    ("JournalReplay", "JournalReplay"): "GRAPH",
    ("MonitorBackwardContext", "MonitorBackwardContextLiveness"): "COUNTS",
    ("OrderedWorkers", "OrderedWorkers"): "GRAPH",
    ("PipelineComposition", "PipelineComposition"): "GRAPH",
    ("SnapshotCollection", "SnapshotCollectionLiveness"): "COUNTS",
}
SUCCESS = "Model checking completed. No error has been found."
METHOD = "Checked with immutable action frames."


@dataclasses.dataclass(frozen=True, kw_only=True)
class Receipt:
    """Rows reference the same value tables and retain ordered edge occurrences."""

    fields: tuple[str, ...]
    values: tuple[tuple[str, ...], ...]
    rows: tuple[tuple[int, ...], ...]
    initial: frozenset[int]
    outgoing: tuple[tuple[tuple[str, int], ...], ...]
    generated: int

    @property
    def state_count(self) -> int:
        """Count every row in this complete state inventory."""
        return len(self.rows)

    def states(self) -> list[dict[str, str]]:
        """Give existing conformance adapters their raw TLC valuations.

        Returns:
            All states in discovery order, sharing immutable field values.
        """
        return [
            dict(
                zip(
                    self.fields,
                    (
                        table[index]
                        for table, index in zip(self.values, row, strict=True)
                    ),
                    strict=True,
                ),
            )
            for row in self.rows
        ]

    def graph(self) -> tests.formal.helpers.tlc.Graph:
        """Retain node identity, initial marks, and every ordered successor.

        Returns:
            The complete graph in the existing conformance representation.
        """
        return tests.formal.helpers.tlc.Graph(
            states=dict(enumerate(self.states())),
            initial=self.initial,
            outgoing={
                source: tuple(
                    tests.formal.helpers.tlc.Edge(
                        source=source,
                        target=target,
                        action=action,
                    )
                    for action, target in successors
                )
                for source, successors in enumerate(self.outgoing)
                if successors
            },
        )


def path(directory: pathlib.Path, module: str, config: str) -> pathlib.Path | None:
    """Allow only the finite configurations reviewed by the Java checker.

    Returns:
        The run-local receipt path when the configuration is eligible.
    """
    if EXPORTS.get((module, config)) in {"GRAPH", "STATES"}:
        return directory / f"frames-{config}.pfr"
    return None


def decoded(value: bytes) -> str:
    """Keep the raw value rendered by the official TLC value implementation.

    Returns:
        The complete UTF-8 value from the receipt's base64 field.
    """
    return base64.b64decode(value, validate=True).decode()


def tables(
    stream: typing.BinaryIO,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Read the field inventory and its ordered immutable value tables.

    Returns:
        Field names and their value tables in the original order.
    """
    record, *names = stream.readline().rstrip(b"\n").split(b"\t")
    fields = tuple(map(decoded, names))
    assert record == b"F"
    assert fields
    assert len(set(fields)) == len(fields)
    assert all(field.isidentifier() for field in fields)
    values = []
    for index in range(len(fields)):
        record, identifier, *data = stream.readline().rstrip(b"\n").split(b"\t")
        assert record == b"V"
        assert int(identifier) == index
        assert data
        values.append(tuple(map(decoded, data)))
    return fields, tuple(values)


def read(
    file: pathlib.Path,
    *,
    with_edges: bool = True,
) -> Receipt | tests.formal.helpers.tlc_frame_wire.Receipt:
    """Reject incomplete inventories and keep repeated outgoing edges in order.

    Returns:
        Immutable state tables and the requested successor inventory.
    """
    with file.open("rb") as stream:
        if stream.peek(4).startswith(tests.formal.helpers.tlc_frame_wire.MAGIC):
            return tests.formal.helpers.tlc_frame_wire.read(
                stream,
                with_edges=with_edges,
            )
        fields, values = tables(stream)
        return read_rows(stream, fields, values, with_edges=with_edges)


def read_rows(
    stream: typing.BinaryIO,
    fields: tuple[str, ...],
    values: tuple[tuple[str, ...], ...],
    *,
    with_edges: bool,
) -> Receipt:
    """Decode the ordered source rows, successor occurrences, and terminal counts.

    Returns:
        A complete receipt with every required state and edge.

    Raises:
        ValueError: If a record has an unexpected kind or the footer is absent.
    """
    widths = tuple(map(len, values))
    initials: set[int] = set()
    rows: list[tuple[int, ...]] = []
    outgoing: list[list[tuple[str, int]]] = []
    actions: dict[bytes, str] = {}
    edge_count = 0
    for line in stream:
        assert line.endswith(b"\n"), "incomplete frame record"
        record, _, data = line[:-1].partition(b"\t")
        match record:
            case b"I":
                initial = int(data)
                assert not rows
                assert initial >= 0
                assert initial not in initials
                initials.add(initial)
            case b"S":
                row = tuple(map(int, data.split(b"\t")))
                assert row[0] == len(rows)
                assert all(
                    0 <= value < width
                    for value, width in zip(row[1:], widths, strict=True)
                )
                rows.append(row[1:])
                if with_edges:
                    outgoing.append([])
            case b"E":
                assert rows, "an edge must follow its source"
                edge_count += 1
                if with_edges:
                    source, action, target = data.split(b"\t")
                    assert int(source) == len(rows) - 1
                    assert action
                    if action not in actions:
                        actions[action] = action.decode()
                    outgoing[-1].append((actions[action], int(target)))
            case b"C":
                assert not stream.read(1), "unexpected data after frame counts"
                return complete(
                    Receipt(
                        fields=fields,
                        values=values,
                        rows=tuple(rows),
                        initial=frozenset(initials),
                        outgoing=tuple(map(tuple, outgoing)),
                        generated=len(initials) + edge_count,
                    ),
                    edge_count,
                    data,
                )
            case _:
                message = f"Unknown frame record {record!r}"
                raise ValueError(message)
    message = "Incomplete frame receipt"
    raise ValueError(message)


def complete(
    receipt: Receipt,
    edge_count: int,
    footer: bytes,
) -> Receipt:
    """Check the complete inventory before constructing immutable evidence.

    Returns:
        The validated shared state and successor tables.
    """
    generated, states, initial_count, edges = map(int, footer.split(b"\t"))
    assert states == len(receipt.rows) > 0
    assert initial_count == len(receipt.initial) > 0
    assert max(receipt.initial) < states
    assert edges == edge_count
    assert generated == receipt.generated
    if receipt.outgoing:
        assert len(set(receipt.rows)) == states, "duplicate state rows"
        check_reachability(receipt.initial, receipt.outgoing)
    return receipt


def check_reachability(
    initials: frozenset[int],
    outgoing: tuple[tuple[tuple[str, int], ...], ...],
) -> None:
    """Require a real path from an initial state to every published state."""
    reached = set(initials)
    pending = list(initials)
    while pending:
        for _, target in outgoing[pending.pop()]:
            assert 0 <= target < len(outgoing), "unknown frame edge target"
            if target not in reached:
                reached.add(target)
                pending.append(target)
    assert len(reached) == len(outgoing), "unreachable frame rows"


async def check(
    module: str,
    config: str,
    directory: pathlib.Path,
    worker: tests.formal.helpers.tlc_worker.Worker | None,
) -> str | None:
    """Publish fresh frame evidence only after a complete qualified check.

    Returns:
        Successful check diagnostics, or None when standard TLC must run.
    """
    mode = EXPORTS.get((module, config))
    if worker is None or not worker.framed or mode is None:
        return None
    destination = path(directory, module, config)
    with tempfile.TemporaryDirectory(prefix="frames-", dir=directory) as temporary:
        staging = pathlib.Path(temporary)
        export = staging / "complete.pfr"
        result = await worker.execute(
            [
                tests.formal.helpers.tlc_worker.FRAME_REQUEST,
                module,
                config,
                str(worker.cwd),
                str(export),
                mode,
            ],
            staging,
            maximum_seconds=180,
        )
        if result.returncode == tests.formal.helpers.tlc_worker.FRAME_UNSUPPORTED:
            return None
        assert result.returncode == 0, result.stdout + result.stderr
        if mode == "COUNTS":
            generated, states = counts(export)
        else:
            with export.open("rb") as stream:
                receipt = await asyncio.to_thread(
                    tests.formal.helpers.tlc_frame_wire.read,
                    stream,
                    with_edges=mode == "GRAPH",
                )
            assert bool(receipt.degrees) == (mode == "GRAPH")
            generated, states = receipt.generated, receipt.state_count
            assert destination is not None
            export.chmod(0o444)
            export.replace(destination)
    return (
        f"{SUCCESS}\n"
        f"{generated} states generated, {states} distinct states "
        f"found, 0 states left on queue.\n{METHOD}"
    )


def counts(file: pathlib.Path) -> tuple[int, int]:
    """Validate a complete no-export result without publishing a graph receipt.

    Returns:
        The generated and distinct state counts from the completed check.
    """
    with file.open("rb") as stream:
        data = stream.read(128)
        assert data.endswith(b"\n")
        assert not stream.read(1)
    marker, *fields = data[:-1].split(b"\t")
    assert marker == b"C"
    assert all(field.isdigit() for field in fields)
    generated, states, initials, edges = map(int, fields)
    assert (
        0
        < initials
        <= states
        <= generated
        <= tests.formal.helpers.tlc_frame_wire.MAX_STATES
    )
    assert initials + edges == generated
    return generated, states
