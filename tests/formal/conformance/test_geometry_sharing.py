import itertools

import pytest
import shapely

import spatial_data.geometry_pool
import tests.formal.helpers.geometry_sharing
import tests.formal.helpers.oracle


def test_compressed_trie_matches_lean_at_every_small_history_prefix() -> None:
    assert (
        tests.formal.helpers.geometry_sharing.compare_histories(
            tests.formal.helpers.geometry_sharing.compact_histories(),
        )
        == tests.formal.helpers.geometry_sharing.SMALL_TRANSITIONS
    )


def test_insertion_permutations_preserve_exact_colliding_payloads() -> None:
    alphabet = ((0, 0), (0, 1), (1, 2), (3, 3), (128, 4))
    assert (
        tests.formal.helpers.geometry_sharing.compare_histories(
            itertools.permutations(alphabet),
        )
        == tests.formal.helpers.geometry_sharing.PERMUTATION_TRANSITIONS
    )


def test_sorted_full_width_digests_preserve_depth_and_snapshots() -> None:
    history = tuple((1 << bit, bit % 5) for bit in range(256))
    assert (
        tests.formal.helpers.geometry_sharing.compare_histories(
            (history, tuple(reversed(history))),
        )
        == tests.formal.helpers.geometry_sharing.WIDTH_TRANSITIONS
    )


def test_packed_prefixes_decode_to_the_complete_ordered_reference() -> None:
    alphabet = ((0, 0), (0, 1), (1, 2), (3, 3), (128, 4))
    histories = (
        (),
        *tests.formal.helpers.geometry_sharing.compact_histories(),
        *itertools.permutations(alphabet),
    )
    assert tests.formal.helpers.geometry_sharing.checked_prefixes(
        histories,
    ) == tests.formal.helpers.oracle.evaluate(
        [
            "tree-prefixes "
            + tests.formal.helpers.geometry_sharing.encoded_entries(history)
            for history in histories
        ],
        executable="oraclePresentationFlow",
    )


@pytest.mark.parametrize(
    ("response", "diagnostic"),
    [
        pytest.param((1,), "counts", id="missing-count"),
        pytest.param((1, 1), "counts", id="missing-root"),
        pytest.param((1, 2, 4, 0, 0, 1, 0, 0), "length", id="truncated-node"),
        pytest.param((1, 2, 4, 0, 2, 1, 0, 0, 0), "digest", id="unknown-digest"),
        pytest.param(
            (1, 2, 5, 0, 0, 2, 0, 0, 0, 0),
            "constructor fields",
            id="duplicate-payload",
        ),
        pytest.param(
            (1, 2, 5, 1, 0, 1, 0, 0, 0, 0),
            "constructor fields",
            id="forward-child",
        ),
        pytest.param(
            (2, 2, 4, 0, 0, 1, 0, 4, 0, 0, 1, 0, 0, 1),
            "node table",
            id="duplicate-node-token",
        ),
        pytest.param((1, 2, 4, 0, 0, 1, 0, 0, 1), "root", id="unknown-root"),
        pytest.param(
            (2, 2, 4, 0, 0, 1, 0, 4, 0, 1, 1, 1, 0, 0),
            "Unused packed tree nodes",
            id="unused-node",
        ),
        pytest.param(
            (3, 2, 4, 0, 0, 1, 0, 4, 0, 1, 1, 1, 5, 1, 0, 5, 0, 1, 2, 2),
            "prefix node bound",
            id="oversized-expansion",
        ),
    ],
)
def test_unpack_prefixes_rejects_malformed_tables(
    response: tuple[int, ...],
    diagnostic: str,
) -> None:
    with pytest.raises(ValueError, match=diagnostic):
        tests.formal.helpers.geometry_sharing.unpack_prefixes(
            ((11, 0), (17, 1)),
            response,
        )


@pytest.mark.parametrize("collision", [False, True])
def test_concurrent_pool_publishes_one_object_per_exact_payload(
    monkeypatch: pytest.MonkeyPatch,
    *,
    collision: bool,
) -> None:
    if collision:
        monkeypatch.setattr(
            spatial_data.geometry_pool,
            "geometry_digest",
            lambda _: bytes(32),
        )
    assert (
        tests.formal.helpers.geometry_sharing.concurrent_pool()
        == tests.formal.helpers.geometry_sharing.CONCURRENT_REQUESTS
    )


def test_geometry_keys_collision_classes_match_proved_encoding_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_data.geometry_pool,
        "geometry_digest",
        lambda _encoded: bytes(32),
    )
    geometries = [
        shapely.from_wkb(encoded)
        for encoded in tests.formal.helpers.geometry_sharing.catalogue()
    ]
    canonical = list(dict.fromkeys(geometry.wkb for geometry in geometries))
    commands = []
    observed = []
    for order in itertools.permutations(range(len(geometries))):
        registry = spatial_data.geometry_pool.GeometryKeys()
        history = []
        for index in (*order, *reversed(order)):
            geometry = geometries[index]
            payload = canonical.index(geometry.wkb)
            history.append(payload)
            digest, position = registry.key(geometry)
            assert digest == bytes(32)
            commands.append(
                f"encoding-position {payload} " + " ".join(map(str, history)),
            )
            observed.append((position,))
    assert observed == tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oraclePresentationFlow",
    )
