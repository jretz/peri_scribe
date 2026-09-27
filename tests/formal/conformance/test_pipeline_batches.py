import collections
import pathlib
import tempfile

import pytest

import tests.formal.helpers.pipeline_batch_checks
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition


@pytest.mark.parametrize("count", [1, 2, 7])
def test_partition_preserves_exact_histories_without_merging_equal_durable_states(
    count: int,
) -> None:
    histories = tests.formal.helpers.pipeline_batch_checks.histories()
    roots = tests.formal.helpers.pipeline_batches.trees(histories)
    batches = tests.formal.helpers.pipeline_batches.partition(roots, count)
    assert len(batches) == count
    assert collections.Counter(
        history
        for batch in batches
        for history in tests.formal.helpers.pipeline_batch_checks.terminal_histories(
            batch,
        )
    ) == collections.Counter(histories)
    assert collections.Counter(branch for batch in batches for branch in batch) == (
        collections.Counter(roots)
    )


def test_replay_copies_complete_real_prefixes_without_sharing_mutable_branch_files(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    histories = tests.formal.helpers.pipeline_batch_checks.histories()
    roots = tests.formal.helpers.pipeline_batches.trees(histories)
    probe = tests.formal.helpers.pipeline_batch_checks.BranchProbe()
    monkeypatch.setattr(
        tests.formal.helpers.pipeline_composition,
        "replay",
        probe.replay,
    )
    results = tests.formal.helpers.pipeline_batches.replay(
        roots,
        tmp_path,
        tests.formal.helpers.pipeline_batch_checks.contract(),
    )
    assert set(results) == set(histories)
    prefixes = {
        history[:length]
        for history in histories
        for length in range(1, len(history) + 1)
    }
    assert set(probe.paths) == prefixes
    assert len(set(probe.directories.values())) == len(prefixes)
    assert all(not directory.exists() for directory in probe.directories.values())
    for history, execution in results.items():
        assert execution is probe.paths[history]


def test_replay_matches_independent_full_histories_across_retained_recovery_states(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_executions: tests.formal.helpers.pipeline_composition.Executions,
) -> None:
    histories = tests.formal.helpers.pipeline_batch_checks.selected_histories(
        pipeline_executions,
    )
    independent = tests.formal.helpers.pipeline_batch_checks.ObservedReplay(
        original=tests.formal.helpers.pipeline_composition.replay,
    )
    for history in histories:
        with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
            execution = None
            for record in history:
                execution = independent.replay(
                    record,
                    pathlib.Path(directory) / "2026",
                    pipeline_executions.checked,
                    execution,
                )
    shared = tests.formal.helpers.pipeline_batch_checks.ObservedReplay(
        original=tests.formal.helpers.pipeline_composition.replay,
    )
    monkeypatch.setattr(
        tests.formal.helpers.pipeline_composition,
        "replay",
        shared.replay,
    )
    results = tests.formal.helpers.pipeline_batches.replay(
        tests.formal.helpers.pipeline_batches.trees(histories),
        tmp_path,
        pipeline_executions.checked,
    )
    assert results == {history: independent.paths[history] for history in histories}
    assert set(shared.images) == set(independent.images)
    for history, observed in shared.images.items():
        expected = independent.images[history]
        assert observed.directories == expected.directories
        assert {
            name: (value.content, value.mode) for name, value in observed.files.items()
        } == {
            name: (value.content, value.mode) for name, value in expected.files.items()
        }
        output = pathlib.Path("maps") / "PeriScribe Fires 2026.kmz"
        assert observed.files[output] == expected.files[output]
