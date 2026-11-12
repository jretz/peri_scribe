"""Decode one immutable, source-qualified frame receipt in discovery order."""

import array
import collections.abc
import dataclasses
import struct
import sys
import typing

import tests.formal.helpers.tlc


MAGIC = b"PFR2"
MAX_BYTES = 128 * 1024 * 1024
MAX_STATES = 1_000_000
MAX_FIELDS = 20
MAX_VALUES = 65_535


@dataclasses.dataclass(frozen=True, kw_only=True)
class Receipt:
    """Store shared field ordinals and exact ordered successor occurrences."""

    fields: tuple[str, ...]
    values: tuple[tuple[str, ...], ...]
    rows: memoryview
    generated: int
    state_count: int
    initial_count: int
    labels: tuple[str, ...]
    degrees: memoryview
    targets: memoryview
    actions: memoryview

    def projected(
        self,
        names: tuple[str, ...],
        *,
        where: tuple[str, frozenset[str]] | None = None,
    ) -> collections.abc.Iterator[dict[str, str]]:
        """Decode only requested fields of matching rows, in discovery order.

        Yields:
            Selected fields of each matching row in discovery order.
        """
        columns = tuple((self.fields.index(name), name) for name in names)
        tables = tuple((index, name, self.values[index]) for index, name in columns)
        width = len(self.fields)
        rows = self.rows
        offsets: collections.abc.Iterable[int] = range(0, len(rows), width)
        if where is not None:
            field, accepted = where
            column = self.fields.index(field)
            matches = tuple(value in accepted for value in self.values[column])
            offsets = (offset for offset in offsets if matches[rows[offset + column]])
        for offset in offsets:
            yield {name: table[rows[offset + index]] for index, name, table in tables}

    def states(self) -> list[dict[str, str]]:
        """Materialize fresh mutable rows backed by shared immutable field values.

        Returns:
            Independent state dictionaries retaining immutable field values.
        """
        return list(self.projected(self.fields))

    def graph(self) -> tests.formal.helpers.tlc.Graph:
        """Materialize every checked node, initial mark, and ordered edge.

        Returns:
            The complete checked graph in its original order.
        """
        assert self.degrees, "a state-only frame cannot supply a graph"
        offset = 0
        outgoing = {}
        for source, degree in enumerate(self.degrees):
            if degree:
                end = offset + degree
                outgoing[source] = tuple(
                    tests.formal.helpers.tlc.Edge(
                        source=source,
                        target=target,
                        action=self.labels[action],
                    )
                    for action, target in zip(
                        self.actions[offset:end],
                        self.targets[offset:end],
                        strict=True,
                    )
                )
                offset = end
        return tests.formal.helpers.tlc.Graph(
            states=dict(enumerate(self.states())),
            initial=frozenset(range(self.initial_count)),
            outgoing=outgoing,
        )


@dataclasses.dataclass
class Wire:
    """Consume fixed-width bounded fields from immutable input bytes."""

    data: memoryview
    offset: int = 0

    def take(self, size: int) -> memoryview:
        """Read exactly the requested number of bytes or reject truncation.

        Returns:
            An immutable view of the requested bytes.
        """
        before = self.offset
        self.offset += size
        assert 0 <= before <= self.offset <= len(self.data), "truncated frame"
        return self.data[before : self.offset]

    def number(self, width: int) -> int:
        """Read a nonnegative network-order integer.

        Returns:
            The nonnegative integer in the selected bytes.
        """
        return int.from_bytes(self.take(width), "big")

    def text(self) -> str:
        """Keep the full UTF-8 text emitted by TLC's value renderer.

        Returns:
            The complete rendered UTF-8 value.
        """
        return self.take(self.number(4)).tobytes().decode()

    def words(
        self,
        kind: typing.Literal["H", "I"],
        width: int,
        count: int,
    ) -> memoryview:
        """Read fixed-width integers and retain only their immutable native bytes.

        Returns:
            An immutable native-order integer view.
        """
        values = array.array(kind)
        assert values.itemsize == width
        if sys.byteorder == "big":
            return self.take(width * count).cast(kind)
        values.frombytes(self.take(width * count))
        values.byteswap()
        return memoryview(values.tobytes()).cast(kind)


def read(stream: typing.BinaryIO, *, with_edges: bool) -> Receipt:
    """Validate the complete checked inventory before exposing its typed columns.

    Returns:
        The complete ordered state inventory and any exported edges.
    """
    data = stream.read(MAX_BYTES + 1)
    assert len(data) <= MAX_BYTES, "oversized frame receipt"
    wire = Wire(memoryview(data))
    assert wire.take(4) == MAGIC
    exported = wire.number(1)
    assert exported in {0, 1}
    assert not with_edges or exported, "a state-only frame cannot supply a graph"
    generated, states, initials, edges = struct.unpack(">4I", wire.take(16))
    assert 0 < initials <= states <= generated <= MAX_STATES
    assert initials + edges == generated
    fields, tables, rows = state_tables(wire, states)
    labels, degrees, targets, actions = edge_tables(
        wire,
        states=states,
        initials=initials,
        edges=edges,
        exported=bool(exported),
    )
    assert wire.offset == len(data), "unexpected data after frame inventory"
    return Receipt(
        fields=tuple(fields),
        values=tuple(tables),
        rows=rows,
        generated=generated,
        state_count=states,
        initial_count=initials,
        labels=labels,
        degrees=degrees,
        targets=targets,
        actions=actions,
    )


def state_tables(
    wire: Wire,
    states: int,
) -> tuple[list[str], list[tuple[str, ...]], memoryview]:
    """Read field tables and validate every state value code.

    Returns:
        Ordered names, immutable value tables, and encoded state rows.
    """
    columns = wire.number(1)
    assert 0 < columns <= MAX_FIELDS
    fields = []
    tables = []
    for _ in range(columns):
        fields.append(wire.text())
        count = wire.number(2)
        assert 0 < count <= MAX_VALUES
        tables.append(tuple(wire.text() for _ in range(count)))
    assert len(set(fields)) == columns
    assert all(field.isidentifier() for field in fields)
    first = wire.offset
    rows = wire.words("H", 2, states * columns)
    stride = 2 * columns
    assert (
        len({
            wire.data[offset : offset + stride].tobytes()
            for offset in range(first, wire.offset, stride)
        })
        == states
    ), "duplicate state rows"
    for index, table in enumerate(tables):
        assert max(rows[index::columns]) < len(table), "unknown frame value"
    return fields, tables, rows


def edge_tables(
    wire: Wire,
    *,
    states: int,
    initials: int,
    edges: int,
    exported: bool,
) -> tuple[tuple[str, ...], memoryview, memoryview, memoryview]:
    """Read exact ordered edge occurrences and verify each discovery witness.

    Returns:
        The labels and per-source degrees, followed by targets and action codes.
    """
    if not exported:
        empty = memoryview(b"").cast("I")
        return (), empty, empty, memoryview(b"")
    labels = tuple(wire.text() for _ in range(wire.number(1)))
    assert len(set(labels)) == len(labels)
    assert all(labels)
    degrees = wire.words("I", 4, states)
    targets = wire.words("I", 4, edges)
    actions = wire.take(edges)
    assert sum(degrees) == edges
    if edges:
        assert max(actions) < len(labels)
        assert max(targets) < states
    offset = 0
    reached = bytearray(states)
    for source, degree in enumerate(degrees):
        end = offset + degree
        for target in targets[offset:end]:
            if source < target:
                reached[target] = 1
        offset = end
    assert all(reached[initials:]), "unreachable frame rows"
    return labels, degrees, targets, actions
