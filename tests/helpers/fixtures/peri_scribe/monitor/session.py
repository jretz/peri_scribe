"""Provide isolated year directories for framework-independent monitor consumers."""

import pathlib

import pytest


@pytest.fixture
def monitor_year(tmp_path: pathlib.Path) -> pathlib.Path:
    """Use the same year-directory contract as command-line monitoring.

    Args:
        tmp_path: The current test's isolated filesystem.

    Returns:
        An empty directory named for the observed year.
    """
    directory = tmp_path / "2026"
    directory.mkdir()
    return directory
