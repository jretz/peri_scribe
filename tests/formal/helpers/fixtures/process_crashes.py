"""Reuse checked crash contracts while isolating every concrete process lifetime."""

import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.journal_builder
import tests.formal.helpers.log_rotation
import tests.formal.helpers.paths
import tests.formal.helpers.process_crashes
import tests.formal.helpers.product_cache


@pytest.fixture(scope="session")
def crash_marker_contract(
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.paths.Contract[tests.formal.helpers.process_crashes.Marker]:
    """Reuse the complete checked graph across independent fetch crash cases.

    Args:
        formal_corpus_directory: Private checked-artifact storage for this pytest run.

    Returns:
        The exact fetch-only projection of the checked crash and recovery graph.
    """
    return tests.formal.helpers.process_crashes.marker_contract(
        tests.formal.helpers.corpus.graph(
            "FetchCrash",
            "FetchCrash",
            formal_corpus_directory,
        ),
    )


@pytest.fixture(scope="session")
def crash_builder_contract(
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.paths.Contract[
    tests.formal.helpers.journal_builder.Projection
]:
    """Use one full journal exploration for every independently killed builder.

    Args:
        formal_corpus_directory: Private checked-artifact storage for this pytest run.

    Returns:
        The checked publication contract for two fresh input generations.
    """
    return tests.formal.helpers.journal_builder.contracts(
        tests.formal.helpers.corpus.graph(
            "UpdateJournal",
            "UpdateJournal",
            formal_corpus_directory,
        ),
    )[True, True]


@pytest.fixture(scope="session")
def crash_rotation_contract(
    formal_corpus_directory: pathlib.Path,
) -> tests.formal.helpers.paths.Contract[tests.formal.helpers.log_rotation.Projection]:
    """Share graph preparation while each rotation retains its own real files.

    Args:
        formal_corpus_directory: Private checked-artifact storage for this pytest run.

    Returns:
        The checked receipt, archive, and source-retirement contract.
    """
    return tests.formal.helpers.log_rotation.contract(
        tests.formal.helpers.corpus.graph(
            "LogRotation",
            "LogRotation",
            formal_corpus_directory,
        ),
    )


@pytest.fixture(scope="session")
def crash_cache_prefixes(
    formal_corpus_directory: pathlib.Path,
) -> dict[tuple[int, ...], dict[str, str]]:
    """Keep every checked transaction prefix available to separate process tests.

    Args:
        formal_corpus_directory: Private checked-artifact storage for this pytest run.

    Returns:
        Complete traces mapped to the actual pending and committed TLC states.
    """
    return {
        tests.formal.helpers.product_cache.numbers(state["trace"]): state
        for state in tests.formal.helpers.corpus.states(
            "ProductCache",
            "ProductCache",
            formal_corpus_directory,
        )
    }
