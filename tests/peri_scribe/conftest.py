"""Provide isolated fixtures for this test package."""

from __future__ import annotations

import pathlib
import typing

import pytest
import time_machine

import peri_scribe.fires.index
import peri_scribe.kml.builder
import peri_scribe.publication
import peri_scribe.sources.fetching
import tests.main_stubs
import tests.peri_scribe.main_publication_helpers
import tests.peri_scribe.publication_helpers


@pytest.fixture
def scenario(
    run_stubs: typing.Callable[..., tests.main_stubs.RunStubs],
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tests.peri_scribe.main_publication_helpers.Scenario:
    """Start with a published 100-acre map and a downloaded 110-acre update.

    Args:
        run_stubs: The fixture factory replacing external pipeline operations.
        tmp_path: The isolated root for this scenario's files.
        monkeypatch: The fixture installing temporary pipeline substitutes.

    Returns:
        An isolated year with source geometry saved but not acknowledged by publication.
    """
    year = tmp_path / "data/2026"
    year.mkdir(parents=True)
    stubs = run_stubs(changed=True)
    baseline = tests.peri_scribe.publication_helpers.mapping(100)
    inputs = tests.peri_scribe.publication_helpers.collection(
        baseline,
        tests.peri_scribe.publication_helpers.mapping(110, serial=2),
    )
    monkeypatch.setattr(peri_scribe.publication, "collect", lambda _year: inputs)
    output = peri_scribe.kml.builder.kmz_path(year)
    output.parent.mkdir()
    output.write_bytes(b"complete previous KMZ")
    with time_machine.travel(
        tests.peri_scribe.main_publication_helpers.NOW,
        tick=False,
    ):
        peri_scribe.publication.commit(
            year,
            output,
            tests.peri_scribe.publication_helpers.collection(baseline),
            tests.peri_scribe.publication_helpers.publication(baseline).fires,
        )

    def fetch(
        base: pathlib.Path,
        *,
        year: int,
        full: bool,
        build_index: bool,
    ) -> peri_scribe.sources.fetching.FetchResult:
        """Require gated collection to defer indexing until publication is due.

        Args:
            base: The base directory supplied to the fire fetcher.
            year: The requested collection year.
            full: Whether the request forces a full source refresh.
            build_index: Whether indexing was requested; must be false for gated
                fetches.

        Returns:
            The requested collection outcome.
        """
        assert not build_index
        stubs.fetch_calls.append((base, year, full))
        return stubs.fetch_result

    def create(
        year: pathlib.Path,
        *,
        publication_inputs: peri_scribe.publication.Collection | None = None,
    ) -> pathlib.Path:
        """Complete a local file and commit only the inputs supplied by geography.

        Args:
            year: The year directory supplied to the KMZ builder.
            publication_inputs: Frozen sources to acknowledge, or None without a
                publication checkpoint request.

        Returns:
            The output path, as the actual builder does.
        """
        stubs.kmz_calls.append(year)
        output.write_bytes(b"complete new KMZ")
        if publication_inputs is not None:
            assert publication_inputs == inputs
            peri_scribe.publication.commit(year, output, publication_inputs, {})
        return output

    indexed: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.sources.fetching, "fetch_all_feeds", fetch)
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", indexed.append)
    monkeypatch.setattr(peri_scribe.kml.builder, "create_kmz", create)
    return tests.peri_scribe.main_publication_helpers.Scenario(
        year=year,
        stubs=stubs,
        indexed=indexed,
        inputs=inputs,
        output=output,
    )
