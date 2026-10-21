"""Scoped source checksums follow the complete checked authentication graph."""

import pathlib

import pytest

import peri_scribe.sources.authentication
import tests.formal.helpers.corpus
import tests.formal.helpers.source_authentication
import tests.helpers.doubles.peri_scribe.sources.authentication


@pytest.mark.parametrize("inventory_first", [False, True])
def test_file_digest_matches_all_checked_authentication_transitions(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    inventory_first: bool,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "SourceAuthentication",
        "SourceAuthentication",
        tmp_path / "tlc",
    )
    histories = tests.formal.helpers.source_authentication.edge_histories(graph)
    recorder = tests.helpers.doubles.peri_scribe.sources.authentication.DigestRecorder(
        read=peri_scribe.sources.authentication.read_file_digest,
    )
    monkeypatch.setattr(
        peri_scribe.sources.authentication,
        "read_file_digest",
        recorder,
    )
    for index, history in enumerate(histories):
        tests.formal.helpers.source_authentication.replay(
            graph,
            history,
            tmp_path / f"replay-{index}",
            recorder,
            inventory_first=inventory_first,
        )
    assert len(histories) == sum(map(len, graph.outgoing.values()))
