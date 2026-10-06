"""Workers share generated evidence without trusting results from an earlier run."""

import contextlib
import pathlib

import pytest

import tests.formal.helpers.session


SESSION = pytest.StashKey[contextlib.ExitStack]()


def pytest_configure(config: pytest.Config) -> None:
    """Start sharing before xdist and nested pytest inherit their environment.

    Args:
        config: The current controller or child pytest configuration.
    """
    if tests.formal.helpers.session.directory() is None:
        stack = contextlib.ExitStack()
        stack.enter_context(tests.formal.helpers.session.temporary())
        config.stash[SESSION] = stack


def pytest_unconfigure(config: pytest.Config) -> None:
    """The owning controller keeps evidence alive until every worker has exited.

    Args:
        config: The current controller or child pytest configuration.
    """
    if SESSION in config.stash:
        config.stash[SESSION].close()


@pytest.fixture(scope="session")
def formal_corpus_directory() -> pathlib.Path:
    """Use only the temporary root belonging to this controller and its workers.

    Returns:
        One run's shared checked-model directory, also isolated in serial mode.
    """
    directory = tests.formal.helpers.session.directory()
    assert directory is not None
    return directory
