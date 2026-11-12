"""Source races can defer observations, and a stable full fetch repairs them."""

import collections.abc
import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.snapshot_collection
import tests.formal.helpers.snapshot_transport


@pytest.fixture
def snapshot_transport(tmp_path: pathlib.Path) -> collections.abc.Iterator[None]:
    """Keep identical native leaf inputs within this test's private scope.

    Args:
        tmp_path: The real directory holding the checked histories.

    Yields:
        Native conversion, reads, and serialization shared by complete input.
    """
    with tests.formal.helpers.snapshot_transport.shared(tmp_path):
        yield


@pytest.mark.usefixtures("snapshot_transport")
def test_fetch_feed_snapshot_matches_checked_query_interleavings(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "SnapshotCollection",
        "SnapshotCollection",
        tmp_path / "model",
    )
    cases = tests.formal.helpers.snapshot_collection.cases(states)
    expected_cases = 177
    assert len(cases) == expected_cases
    recoveries = tests.formal.helpers.snapshot_collection.completed_recoveries(states)
    seed = tests.formal.helpers.snapshot_collection.write_seed_snapshot(
        tmp_path / "seed",
    )
    stale_cases = 0
    prefixes: dict[
        tests.formal.helpers.snapshot_collection.Collection,
        pathlib.Path,
    ] = {}
    for number, case in enumerate(cases):
        if case.initial not in prefixes:
            prefix = tmp_path / "prefixes" / str(len(prefixes))
            tests.formal.helpers.snapshot_collection.replay_collection(
                case.initial,
                prefix,
                seed,
            )
            prefixes[case.initial] = prefix
        actual = tests.formal.helpers.snapshot_collection.replay_recovery(
            case,
            prefixes[case.initial],
            tmp_path / "cases" / str(number),
        )
        completed = recoveries.get(
            (case.remote, case.remote_marker, case.initial.saved),
            set(),
        )
        assert len(completed) == 1
        assert actual == next(iter(completed))
        assert all(
            not version or actual[index] == version
            for index, version in enumerate(case.remote)
        )
        stale_cases += any(
            version and case.initial.saved[index] != version
            for index, version in enumerate(case.remote)
        )
    expected_prefixes = 70
    assert len(prefixes) == expected_prefixes
    expected_stale_cases = 97
    assert stale_cases == expected_stale_cases
