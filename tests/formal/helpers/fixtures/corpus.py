"""Workers share generated evidence without trusting results from an earlier run."""

import pathlib

import pytest


@pytest.fixture(scope="session")
def formal_corpus_directory(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> pathlib.Path:
    """Use only the temporary root belonging to this controller and its workers.

    Args:
        request: Current worker's pytest configuration.
        tmp_path_factory: Owner of fresh session-specific temporary storage.

    Returns:
        One run's shared checked-model directory, also isolated in serial mode.
    """
    directory = tmp_path_factory.getbasetemp()
    if hasattr(request.config, "workerinput"):
        directory = directory.parent
    return directory / "formal-corpus"
