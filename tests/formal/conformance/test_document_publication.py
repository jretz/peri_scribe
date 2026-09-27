"""Readers see complete JSON, HTML, and Markdown throughout publication."""

import pathlib

import tests.formal.helpers.document_publication
import tests.formal.helpers.tlc


def test_document_writers_match_checked_publication_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "DocumentPublication",
        "DocumentPublication",
        tmp_path / "model",
    )
    expected_cases = 56
    assert (
        tests.formal.helpers.document_publication.replay(
            states,
            tmp_path / "documents",
        )
        == expected_cases
    )
