"""Reuse checked pipeline evidence while every concrete history keeps private files."""

import pathlib

import pytest

import tests.formal.helpers.pipeline_batches
import tests.formal.helpers.pipeline_composition
import tests.formal.helpers.pipeline_corpus


@pytest.fixture(scope="session")
def pipeline_corpus(
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.pipeline_corpus.Prepared:
    """Decode all checked pipeline inputs together only once per worker.

    Args:
        formal_corpus_directory: The shared storage owned by this pytest run.

    Returns:
        The complete path contract, history inventory, and balanced replay partitions.
    """
    return tests.formal.helpers.pipeline_corpus.load(formal_corpus_directory)


@pytest.fixture(scope="session")
def pipeline_executions(
    pipeline_corpus: tests.formal.helpers.pipeline_corpus.Prepared,
) -> tests.formal.helpers.pipeline_composition.Executions:
    """Use the producer's full graph traversal and durable projection.

    Args:
        pipeline_corpus: This worker's independently decoded complete contract.

    Returns:
        The complete path contract and deterministic history inventory.
    """
    return pipeline_corpus.executions


@pytest.fixture(scope="session")
def pipeline_batches(
    pipeline_corpus: tests.formal.helpers.pipeline_corpus.Prepared,
) -> tuple[tuple[tests.formal.helpers.pipeline_batches.Branch, ...], ...]:
    """No shared-prefix optimization may change the checked history inventory.

    Args:
        pipeline_corpus: Complete contract with producer-checked history coverage.

    Returns:
        Balanced intact prefix subtrees covering every original history exactly once.
    """
    return pipeline_corpus.batches
