"""fetch_external_source helper tests for peri_scribe.main."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.main
import peri_scribe.sources.external_sources
from tests.main_stubs import BASE_DIRECTORY


if typing.TYPE_CHECKING:
    import pytest


def test_fetch_external_source_uses_given_year_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = peri_scribe.sources.external_sources.BUILDINGS_SOURCE
    year_directory = pathlib.Path("data/2026")
    fetched: list[tuple[object, pathlib.Path]] = []

    def fetch_external_source(
        source_arg: object,
        directory: pathlib.Path,
    ) -> tuple[pathlib.Path, ...]:
        fetched.append((source_arg, directory))
        return (pathlib.Path("/out.gpkg"),)

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.main.fetch_external_source(source, year_directory)
    assert fetched == [(source, year_directory)]


def test_fetch_external_source_defaults_to_current_year_directory(
    monkeypatch: pytest.MonkeyPatch,
    current_year: typing.Iterator[None],
) -> None:
    source = peri_scribe.sources.external_sources.EVACUATIONS_SOURCE
    fetched: list[tuple[object, pathlib.Path]] = []

    def fetch_external_source(
        source_arg: object,
        directory: pathlib.Path,
    ) -> tuple[pathlib.Path, ...]:
        fetched.append((source_arg, directory))
        return (pathlib.Path("/out.gpkg"),)

    monkeypatch.setattr(
        peri_scribe.sources.external_sources,
        "fetch_external_source",
        fetch_external_source,
    )
    peri_scribe.main.fetch_external_source(source, None)
    assert fetched == [(source, BASE_DIRECTORY / "data" / "2026")]
