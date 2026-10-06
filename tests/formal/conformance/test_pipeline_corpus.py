import collections
import pathlib
import unittest.mock

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.pipeline_batch_checks
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.pipeline_corpus


def test_encode_preserves_complete_contract_and_ordered_history_inventory() -> None:
    expected = tests.formal.helpers.pipeline_batch_checks.corpus_executions()
    encoded = tests.formal.helpers.pipeline_corpus.encode(expected)
    restored = tests.formal.helpers.pipeline_corpus.decode(
        tests.formal.helpers.pipeline_corpus.ADAPTER.validate_json(
            tests.formal.helpers.pipeline_corpus.ADAPTER.dump_json(encoded),
        ),
    )
    assert restored.executions == expected
    assert tuple(restored.executions.histories.items()) == tuple(
        expected.histories.items(),
    )
    assert tuple(
        (node, tuple(fields.items()))
        for node, fields in restored.executions.checked.graph.states.items()
    ) == tuple(
        (node, tuple(fields.items()))
        for node, fields in expected.checked.graph.states.items()
    )
    assert tuple(restored.executions.checked.graph.outgoing.items()) == tuple(
        expected.checked.graph.outgoing.items(),
    )
    assert tuple(restored.executions.checked.actions.items()) == tuple(
        expected.checked.actions.items(),
    )
    assert restored.batches == tests.formal.helpers.pipeline_batches.partition(
        tests.formal.helpers.pipeline_batches.trees(tuple(expected.histories.values())),
        tests.formal.helpers.pipeline_composition.BATCH_COUNT,
    )
    assert collections.Counter(
        history
        for batch in restored.batches
        for history in tests.formal.helpers.pipeline_batch_checks.terminal_histories(
            batch,
        )
    ) == collections.Counter(expected.histories.values())


def test_load_reuses_checked_projection_histories_and_partitions_without_rebuilding(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = tests.formal.helpers.pipeline_batch_checks.corpus_executions()
    graph = unittest.mock.create_autospec(
        tests.formal.helpers.corpus.graph,
        return_value=expected.checked.graph,
    )
    executions = unittest.mock.create_autospec(
        tests.formal.helpers.pipeline_composition.executions,
        return_value=expected,
    )
    partition = unittest.mock.Mock(
        wraps=tests.formal.helpers.pipeline_batches.partition,
    )
    monkeypatch.setattr(tests.formal.helpers.corpus, "graph", graph)
    monkeypatch.setattr(
        tests.formal.helpers.pipeline_composition,
        "executions",
        executions,
    )
    monkeypatch.setattr(tests.formal.helpers.pipeline_batches, "partition", partition)
    cold = tests.formal.helpers.pipeline_corpus.load(tmp_path)
    graph.assert_called_once()
    assert graph.call_args.args[:2] == ("PipelineComposition", "PipelineComposition")
    executions.assert_called_once_with(expected.checked.graph)
    partition.assert_called_once()
    for module, name in (
        (tests.formal.helpers.corpus, "graph"),
        (tests.formal.helpers.pipeline_composition, "executions"),
        (tests.formal.helpers.pipeline_composition, "durable"),
        (tests.formal.helpers.pipeline_composition, "invocation"),
        (tests.formal.helpers.pipeline_batches, "trees"),
        (tests.formal.helpers.pipeline_batches, "partition"),
    ):
        monkeypatch.setattr(
            module,
            name,
            unittest.mock.Mock(side_effect=AssertionError("recomputed pipeline data")),
        )
    assert tests.formal.helpers.pipeline_corpus.load(tmp_path) == cold


def test_load_keeps_worker_graph_fields_and_lookup_maps_independent(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = tests.formal.helpers.pipeline_corpus.encode(
        tests.formal.helpers.pipeline_batch_checks.corpus_executions(),
    )
    monkeypatch.setattr(
        tests.formal.helpers.pipeline_corpus,
        "build",
        unittest.mock.Mock(return_value=encoded),
    )
    original = tests.formal.helpers.pipeline_corpus.load(tmp_path)
    first = tests.formal.helpers.pipeline_corpus.load(tmp_path)
    second = tests.formal.helpers.pipeline_corpus.load(tmp_path)
    assert first == second == original
    node = next(iter(first.executions.checked.graph.states))
    first.executions.checked.graph.states[node]["unprojected"] = "changed"
    first.executions.checked.graph.outgoing.clear()
    first.executions.checked.values.clear()
    first.executions.checked.actions.clear()
    first.executions.histories.clear()
    assert second == original
    assert tests.formal.helpers.pipeline_corpus.load(tmp_path) == original


def test_encode_rejects_partitions_that_omit_complete_histories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tests.formal.helpers.pipeline_batches,
        "partition",
        unittest.mock.Mock(return_value=((),)),
    )
    with pytest.raises(AssertionError):
        tests.formal.helpers.pipeline_corpus.encode(
            tests.formal.helpers.pipeline_batch_checks.corpus_executions(),
        )
