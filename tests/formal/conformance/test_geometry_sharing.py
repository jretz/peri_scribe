import itertools

import pytest

import spatial_data.geometry_pool
import tests.formal.helpers.geometry_sharing


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
