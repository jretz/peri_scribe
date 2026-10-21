from __future__ import annotations

import pathlib
import typing

import peri_scribe.geo.package
import tests.formal.helpers.corpus
import tests.formal.helpers.source_summaries


if typing.TYPE_CHECKING:
    import pytest


def test_read_summaries_matches_every_checked_selection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = tests.formal.helpers.corpus.states(
        "SourceSummaries",
        "SourceSummaries",
        tmp_path / "tlc",
    )
    monkeypatch.setattr(
        peri_scribe.geo.package,
        "read_geopackage",
        tests.formal.helpers.source_summaries.source_contents,
    )
    outcomes = tests.formal.helpers.source_summaries.outcomes(states)
    for index, state in enumerate(outcomes):
        tests.formal.helpers.source_summaries.replay(state, tmp_path / f"case-{index}")
