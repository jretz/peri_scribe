"""Compare the compressed immutable trie with Lean's actual insertion algorithm."""

import collections.abc
import concurrent.futures
import dataclasses
import itertools
import threading

import shapely

import spatial_data.geometry_pool
import tests.formal.helpers.oracle


Entry = tuple[int, int]
State = spatial_data.geometry_pool.GeometryState
type GeometryEncodings = dict[int, tuple[shapely.Geometry, bytes]]
DIGEST_BITS = 256
PACKED_HEADER_FIELDS = 2
NODE_HEADER_FIELDS = 3
BRANCH_CHILDREN = 2
SMALL_TRANSITIONS = 2930
PERMUTATION_TRANSITIONS = 600
WIDTH_TRANSITIONS = 512
CONCURRENT_REQUESTS = 200


def catalogue() -> tuple[bytes, ...]:
    """Exercise canonical bytes distinguishing dimensions, SRID, and geometry type.

    Returns:
        Canonical EWKB payloads assigned exact, collision-independent tokens.
    """
    geometries = (
        shapely.Point(1, 2),
        shapely.Point(1, 2, 3),
        shapely.set_srid(shapely.Point(1, 2), 4326),
        shapely.set_srid(shapely.Point(1, 2), 3857),
        shapely.LineString([(0, 0), (1, 1)]),
    )
    return tuple(shapely.to_wkb(geometry, include_srid=True) for geometry in geometries)


def exact_wkb(geometry: shapely.Geometry, encodings: GeometryEncodings) -> bytes:
    """Share the observed bytes while the immutable geometry remains alive.

    Args:
        geometry: The actual leaf payload being inspected.
        encodings: Exact encodings with strong references owned by this history.

    Returns:
        The geometry's canonical bytes including its spatial reference.
    """
    identity = id(geometry)
    if (retained := encodings.get(identity)) is not None:
        assert retained[0] is geometry
        return retained[1]
    content = shapely.to_wkb(geometry, include_srid=True)
    encodings[identity] = geometry, content
    return content


def describe(
    state: State | None,
    payloads: tuple[bytes, ...],
    encodings: GeometryEncodings,
) -> tuple[tuple[int, ...], list[Entry]]:
    """Check routing and serialize the structure and exact payloads in one traversal.

    See [Geometry sharing](../../../docs/algorithms/geometry-sharing.md).

    Args:
        state: Root of an actual immutable trie snapshot.
        payloads: Exact canonical geometry encodings.
        encodings: Serialized payloads retained across snapshots of this history.

    Returns:
        The structural encoding and exact descendant entries.
    """
    if state is None:
        return (2,), []
    encoding: list[int] = []
    contents: list[Entry] = []
    representatives: set[int] = set()

    def visit(node: State, bound: int, expected_prefix: int | None) -> None:
        """Check the parent's route before adding this node in preorder.

        Args:
            node: The current concrete branch or leaf.
            bound: The number of unconstrained low bits below the parent.
            expected_prefix: Bits imposed by the parent's prefix and child route.
        """
        digest = int.from_bytes(node.digest)
        assert expected_prefix is None or digest >> bound == expected_prefix
        split = node.split_bit
        if split is None:
            assert node.smaller is None
            assert node.larger is None
            values = tuple(
                payloads.index(exact_wkb(geometry, encodings))
                for geometry in node.geometries
            )
            assert values
            assert len(set(values)) == len(values)
            encoding.extend((0, digest, len(values), *values))
            contents.extend((digest, value) for value in values)
            return
        assert not node.geometries
        assert node.smaller is not None
        assert node.larger is not None
        assert 0 < split <= bound
        encoding.extend((1, digest, split))
        representatives.add(digest)
        smaller_prefix = (digest >> split) << 1
        visit(node.smaller, split - 1, smaller_prefix)
        visit(node.larger, split - 1, smaller_prefix | 1)

    visit(state, DIGEST_BITS, None)
    # The matching leaf shares every ancestor route of its representative branch.
    assert representatives <= {digest for digest, _ in contents}
    return tuple(encoding), contents


def encoded_entries(history: collections.abc.Iterable[Entry]) -> str:
    """Encode actual insertion entries for the proved model.

    Args:
        history: Digest and canonical byte-token observations.

    Returns:
        Entries in their original order, including repeated occurrences.
    """
    return " ".join(f"{digest},{payload}" for digest, payload in history)


@dataclasses.dataclass(frozen=True, kw_only=True)
class PackedNode:
    """Keep the full node tokens and references to its ordered children."""

    tokens: tuple[int, ...]
    children: tuple[int, ...] = ()


def decode_node(
    record: tuple[int, ...],
    *,
    digests: tuple[int, ...],
    payloads: frozenset[int],
    preceding: int,
) -> PackedNode:
    """Accept only exact digest and payload values and backward child references.

    Args:
        record: The oracle's complete length-framed node fields.
        digests: Exact input digests in their order of first occurrence.
        payloads: Exact payload identifiers from the current insertion history.
        preceding: Number of nodes available as children.

    Returns:
        One ordered node with its full digest restored.

    Raises:
        ValueError: If a constructor or any of its fields is invalid.
    """
    if len(record) < NODE_HEADER_FIELDS:
        message = "Incomplete packed tree node"
        raise ValueError(message)
    kind, ordinal, size = record[:NODE_HEADER_FIELDS]
    if not 0 <= ordinal < len(digests):
        message = "Unknown packed tree digest"
        raise ValueError(message)
    fields = record[NODE_HEADER_FIELDS:]
    digest = digests[ordinal]
    if kind == 0 and size == len(fields) > 0:
        values = set(fields)
        if values <= payloads and len(values) == size:
            return PackedNode(tokens=(kind, digest, size, *fields))
    if (
        kind == 1
        and 0 < size <= DIGEST_BITS
        and len(fields) == BRANCH_CHILDREN
        and all(0 <= child < preceding for child in fields)
    ):
        return PackedNode(tokens=(kind, digest, size), children=fields)
    message = "Invalid packed tree constructor fields"
    raise ValueError(message)


def unpack_prefixes(
    history: tuple[Entry, ...],
    response: tuple[int, ...],
) -> tuple[int, ...]:
    """Restore every full prefix description from exact ordered node references.

    Args:
        history: The ordered digest and payload inputs used to build the trees.
        response: The oracle's node and root counts, framed nodes, and ordered roots.

    Returns:
        The original sequence of length-framed tree descriptions.

    Raises:
        ValueError: If the oracle names an invalid, aliased, or unused node.
    """
    if len(response) < PACKED_HEADER_FIELDS:
        message = "Missing packed tree counts"
        raise ValueError(message)
    count, roots = response[:PACKED_HEADER_FIELDS]
    if (
        roots != len(history)
        or not 0 <= count <= roots**2
        or roots > len(response) - PACKED_HEADER_FIELDS
    ):
        message = "Invalid packed tree counts"
        raise ValueError(message)
    digests = tuple(dict.fromkeys(digest for digest, _ in history))
    payloads = frozenset(payload for _, payload in history)
    records: list[PackedNode] = []
    offset = PACKED_HEADER_FIELDS
    boundary = len(response) - roots
    for preceding in range(count):
        if (
            offset >= boundary
            or not NODE_HEADER_FIELDS <= response[offset] < boundary - offset
        ):
            message = "Invalid packed tree node length"
            raise ValueError(message)
        end = offset + 1 + response[offset]
        records.append(
            decode_node(
                response[offset + 1 : end],
                digests=digests,
                payloads=payloads,
                preceding=preceding,
            ),
        )
        offset = end
    if offset != boundary or len(set(records)) != count:
        message = "Invalid packed tree node table"
        raise ValueError(message)
    return expand_roots(tuple(records), response[boundary:])


def expand_roots(
    records: tuple[PackedNode, ...],
    roots: tuple[int, ...],
) -> tuple[int, ...]:
    """Decode each occurrence in preorder while bounding untrusted expansion.

    Args:
        records: Unique validated nodes ordered after their children.
        roots: One root for each nonempty prefix in insertion order.

    Returns:
        Full framed descriptions, with repeated node occurrences preserved.

    Raises:
        ValueError: If a root or its expansion is outside the prefix bounds.
    """
    output: list[int] = []
    reached: set[int] = set()
    for length, root in enumerate(roots, start=1):
        if not 0 <= root < len(records):
            message = "Unknown packed tree root"
            raise ValueError(message)
        start = len(output)
        output.append(0)
        pending = [root]
        remaining = 2 * length - 1
        while pending:
            if not remaining:
                message = "Packed tree exceeds its prefix node bound"
                raise ValueError(message)
            remaining -= 1
            node = pending.pop()
            reached.add(node)
            record = records[node]
            output.extend(record.tokens)
            pending.extend(reversed(record.children))
        output[start] = len(output) - start - 1
    if len(reached) != len(records):
        message = "Unused packed tree nodes"
        raise ValueError(message)
    return tuple(output)


def checked_prefixes(
    histories: collections.abc.Sequence[tuple[Entry, ...]],
) -> list[tuple[int, ...]]:
    """Read exact prefix descriptions produced by the proved insertion algorithm.

    Args:
        histories: Every requested insertion history in caller order.

    Returns:
        Each original complete framed description in the same order.
    """
    responses = tests.formal.helpers.oracle.evaluate(
        [f"packed-tree-prefixes {encoded_entries(history)}" for history in histories],
        executable="oraclePresentationFlow",
    )
    return list(map(unpack_prefixes, histories, responses, strict=True))


def compare_histories(histories: collections.abc.Iterable[tuple[Entry, ...]]) -> int:
    """Check resulting nodes, selected old snapshots, and repeated object identity.

    Args:
        histories: Insertion sequences including collisions and repeated inputs.

    Returns:
        Number of actual persistent insertion transitions checked.
    """
    payloads = catalogue()
    requested = []
    observed = []
    transitions = 0
    for history in histories:
        state = None
        identities: dict[Entry, shapely.Geometry] = {}
        encodings: GeometryEncodings = {}
        snapshots: list[tuple[State, tuple[int, ...]]] = []
        description_tokens: list[int] = []
        for index, (digest, payload) in enumerate(history):
            previous = state
            state, geometry = spatial_data.geometry_pool.shared_geometry(
                state,
                digest.to_bytes(32),
                payloads[payload],
            )
            assert shapely.to_wkb(geometry, include_srid=True) == payloads[payload]
            if (digest, payload) in identities:
                assert geometry is identities[digest, payload]
                assert state is previous
            else:
                identities[digest, payload] = geometry
            actual, contents = describe(state, payloads, encodings)
            assert set(contents) == set(history[: index + 1])
            for old, description in snapshots[:: max(1, len(snapshots) // 3)]:
                assert describe(old, payloads, encodings)[0] == description
            snapshots.append((state, actual))
            description_tokens.extend((len(actual), *actual))
        requested.append(history)
        observed.append(tuple(description_tokens))
        transitions += len(history)
    assert observed == checked_prefixes(requested)
    return transitions


def compact_histories() -> tuple[tuple[Entry, ...], ...]:
    """Cover collisions and both directions of splitting before and below a branch.

    Returns:
        Every nonempty history through length four over five exact entries.
    """
    alphabet = ((0, 0), (0, 1), (1, 2), (3, 3), (128, 4))
    return tuple(
        history
        for length in range(1, 5)
        for history in itertools.product(alphabet, repeat=length)
    )


def concurrent_pool() -> int:
    """Check the actual lock boundary with simultaneous canonical payload collisions.

    Returns:
        Number of concurrent requests, each checked for complete and shared content.
    """
    payloads = catalogue()
    pool = spatial_data.geometry_pool.GeometryPool()
    worker_count = 4
    barrier = threading.Barrier(worker_count)

    def worker(offset: int) -> list[tuple[int, shapely.Geometry]]:
        """Overlap workers while each requests every exact payload repeatedly.

        Args:
            offset: Distinct starting position within the shared byte catalogue.

        Returns:
            Every request's payload token and actual decoded object.
        """
        barrier.wait(timeout=10)
        return [
            (index, pool.from_wkb(payloads[index]))
            for position in range(25)
            for index in [(offset + position) % len(payloads)]
        ]

    # Paired offsets give each wave simultaneous identical-payload lookups while
    # retaining all eight original offsets.
    offsets = (0, 5, 1, 6, 2, 7, 3, 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(itertools.chain.from_iterable(executor.map(worker, offsets)))
    for index in range(len(payloads)):
        geometries = [geometry for token, geometry in results if token == index]
        assert len({id(geometry) for geometry in geometries}) == 1
        assert shapely.to_wkb(geometries[0], include_srid=True) == payloads[index]
    states = pool.states()
    contents = []
    for index, state in enumerate(states):
        _, shard_entries = describe(state, payloads, {})
        assert all(key % len(states) == index for key, _ in shard_entries)
        contents.extend(shard_entries)
    expected = {
        (int.from_bytes(spatial_data.geometry_pool.geometry_digest(payload)), index)
        for index, payload in enumerate(payloads)
    }
    assert set(contents) == expected
    assert len(contents) == len(payloads)
    encoded = encoded_entries(contents)
    queries = list(
        itertools.product(
            {key for key, _ in expected},
            range(len(payloads)),
        ),
    )
    answers = tests.formal.helpers.oracle.evaluate(
        [f"lookup {key} {payload} {encoded}" for key, payload in queries],
        executable="oraclePresentationFlow",
    )
    assert answers == [(int(query in expected),) for query in queries]
    return len(results)
