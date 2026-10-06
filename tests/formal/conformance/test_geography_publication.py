"""Publication retries and acknowledgment preserve one complete checked execution."""

import pathlib

import pytest

import tests.formal.helpers.corpus
import tests.formal.helpers.geography_publication
import tests.formal.helpers.publication_paths


def test_geography_publication_continuous_recovery(tmp_path: pathlib.Path) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "GeographyPublication",
        "GeographyPublication",
        tmp_path / "model",
    )
    expected = 44
    assert (
        tests.formal.helpers.geography_publication.replay(
            graph,
            tmp_path / "geography",
        )
        == expected
    )


def test_publication_rejects_reachable_signature_before_bytes(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "GeographyPublication",
        "GeographyPublication",
        tmp_path / "model",
    )
    contract = tests.formal.helpers.publication_paths.contract(graph, forced=False)
    old = (0, 0, (0, 0, True, True), (0, 0, True, True), True)
    reordered = (0, 0, (1, 1, True, True), (0, 0, True, True), True)
    assert reordered in contract.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC execution"):
        contract.start(old).observe(reordered)
