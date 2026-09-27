"""Reuse checked pipeline evidence while every concrete history keeps private files."""

import collections
import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition


@pytest.fixture(scope="session")
def pipeline_executions(
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.pipeline_composition.Executions:
    """Decode one run's checked corpus only once per worker.

    Args:
        formal_corpus_directory: The shared storage owned by this pytest run.

    Returns:
        The complete path contract and deterministic history inventory.
    """
    return tests.formal.helpers.pipeline_composition.executions(
        tests.formal.helpers.corpus.graph(
            "PipelineComposition",
            "PipelineComposition",
            formal_corpus_directory,
        ),
    )


@pytest.fixture(scope="session")
def pipeline_batches(
    pipeline_executions: tests.formal.helpers.pipeline_composition.Executions,
) -> tuple[tuple[tests.formal.helpers.pipeline_batches.Branch, ...], ...]:
    """No shared-prefix optimization may change the checked history inventory.

    Args:
        pipeline_executions: The complete checked graph and original history catalogue.

    Returns:
        Balanced intact prefix subtrees covering every original history exactly once.
    """
    histories = tuple(pipeline_executions.histories.values())
    batches = tests.formal.helpers.pipeline_batches.partition(
        tests.formal.helpers.pipeline_batches.trees(histories),
        tests.formal.helpers.pipeline_composition.BATCH_COUNT,
    )
    assert collections.Counter(
        history
        for batch in batches
        for history in tests.formal.helpers.pipeline_batches.histories(batch)
    ) == collections.Counter(histories)
    return batches
