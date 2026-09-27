"""Compare the compressed immutable trie with Lean's actual insertion algorithm."""

import collections.abc
import concurrent.futures
import itertools
import threading

import shapely

import spatial_data.geometry_pool
import tests.formal.helpers.oracle


Entry = tuple[int, int]
State = spatial_data.geometry_pool.GeometryState
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


def entries(state: State | None, payloads: tuple[bytes, ...]) -> list[Entry]:
    """Project full decoded payload bytes independently of the digest.

    Args:
        state: Actual immutable root returned by production insertion.
        payloads: Canonical bytes defining exact token equality.

    Returns:
        Every exact digest/payload pair retained by the leaves.
    """
    if state is None:
        return []
    if state.split_bit is None:
        return [
            (
                int.from_bytes(state.digest),
                payloads.index(shapely.to_wkb(geometry, include_srid=True)),
            )
            for geometry in state.geometries
        ]
    return entries(state.smaller, payloads) + entries(state.larger, payloads)


def representation(
    state: State | None,
    payloads: tuple[bytes, ...],
    bound: int = 256,
) -> tuple[int, ...]:
    """Check routing and decreasing split depths before describing actual nodes.

    Args:
        state: Root of an actual immutable trie snapshot.
        payloads: Byte catalogue used for exact leaf identification.
        bound: Maximum permitted split bit below the parent.

    Returns:
        A complete structural serialization including branch representatives.
    """
    return describe(state, payloads, bound)[0]


def describe(
    state: State | None,
    payloads: tuple[bytes, ...],
    bound: int,
) -> tuple[tuple[int, ...], list[Entry]]:
    """Visit each node once so deep digest paths remain practical to check.

    Args:
        state: The current compressed trie node.
        payloads: Exact canonical geometry encodings.
        bound: Highest legal split bit at this node.

    Returns:
        Its structural encoding and exact descendant entries.
    """
    if state is None:
        return (2,), []
    digest = int.from_bytes(state.digest)
    if state.split_bit is None:
        assert state.smaller is None
        assert state.larger is None
        contents = entries(state, payloads)
        values = tuple(payload for _, payload in contents)
        assert values
        assert len(set(values)) == len(values)
        return (0, digest, len(values), *values), contents
    assert not state.geometries
    assert state.smaller is not None
    assert state.larger is not None
    split = state.split_bit
    assert 0 < split <= bound
    small_shape, small = describe(state.smaller, payloads, split - 1)
    large_shape, large = describe(state.larger, payloads, split - 1)
    contents = small + large
    assert all(not (key >> (split - 1)) & 1 for key, _ in small)
    assert all((key >> (split - 1)) & 1 for key, _ in large)
    assert digest in {key for key, _ in contents}
    assert all(key >> split == digest >> split for key, _ in contents)
    return (1, digest, split, *small_shape, *large_shape), contents


def request(history: collections.abc.Iterable[Entry]) -> str:
    """Encode one actual insertion sequence for the proved model.

    Args:
        history: Digest and canonical byte-token observations.

    Returns:
        A tree request preserving every insertion and repeated occurrence.
    """
    return "tree" + "".join(f" {digest},{payload}" for digest, payload in history)


def compare_histories(histories: collections.abc.Iterable[tuple[Entry, ...]]) -> int:
    """Check every resulting node, old snapshot, and repeated object identity.

    Args:
        histories: Insertion sequences including collisions and repeated inputs.

    Returns:
        Number of actual persistent insertion transitions checked.
    """
    payloads = catalogue()
    commands = []
    observed = []
    for history in histories:
        state = None
        identities: dict[Entry, shapely.Geometry] = {}
        snapshots: list[tuple[State, tuple[int, ...]]] = []
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
            actual = representation(state, payloads)
            assert set(entries(state, payloads)) == set(history[: index + 1])
            for old, description in snapshots[:: max(1, len(snapshots) // 3)]:
                assert representation(old, payloads) == description
            snapshots.append((state, actual))
            commands.append(request(history[: index + 1]))
            observed.append(actual)
    assert observed == tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oraclePresentationFlow",
    )
    return len(observed)


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
    barrier = threading.Barrier(8)

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

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(itertools.chain.from_iterable(executor.map(worker, range(8))))
    for index in range(len(payloads)):
        geometries = [geometry for token, geometry in results if token == index]
        assert len({id(geometry) for geometry in geometries}) == 1
        assert shapely.to_wkb(geometries[0], include_srid=True) == payloads[index]
    representation(pool.state, payloads)
    contents = entries(pool.state, payloads)
    expected = {
        (int.from_bytes(spatial_data.geometry_pool.geometry_digest(payload)), index)
        for index, payload in enumerate(payloads)
    }
    assert set(contents) == expected
    assert len(contents) == len(payloads)
    encoded = request(contents).removeprefix("tree")
    queries = list(
        itertools.product(
            {key for key, _ in expected},
            range(len(payloads)),
        ),
    )
    answers = tests.formal.helpers.oracle.evaluate(
        [f"lookup {key} {payload}{encoded}" for key, payload in queries],
        executable="oraclePresentationFlow",
    )
    assert answers == [(int(query in expected),) for query in queries]
    return len(results)
