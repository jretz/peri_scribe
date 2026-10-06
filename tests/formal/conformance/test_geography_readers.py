"""Successful downstream reads require one authenticated geography generation."""

import pathlib

import tests.formal.helpers.corpus
import tests.formal.helpers.geography_readers


def test_read_derived_layers_matches_checked_generation_decisions(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "GeographyReaders",
        "GeographyReaders",
        tmp_path / "model",
    )
    tests.formal.helpers.geography_readers.replay(graph, tmp_path / "geography")
