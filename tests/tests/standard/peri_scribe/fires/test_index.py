"""Tests for peri_scribe.fires.index."""

from __future__ import annotations

import json
import pathlib

import pydantic
import pytest

import peri_scribe.execution
import peri_scribe.fires.classification
import peri_scribe.fires.generation
import peri_scribe.fires.index
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.output
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.sources
import tests.helpers.factories.peri_scribe.models


def test_index_fire_sources_reuses_completed_classification_in_execution(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    with peri_scribe.execution.sharing():
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        first = peri_scribe.fires.index.load_fire_index(tmp_path)
        monkeypatch.setattr(
            peri_scribe.fires.classification,
            "classify_fire_sources",
            tests.helpers.doubles.errors.raising_stub(
                AssertionError("Repeated classification"),
            ),
        )
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        second = peri_scribe.fires.index.load_fire_index(tmp_path)

    assert second == first


def test_fire_index_entries_sorts_fires_and_paths() -> None:
    sources_directory = pathlib.Path("/index/sources")
    sources = [
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(
                name="zulu",
                status=tests.helpers.factories.peri_scribe.models.INACTIVE,
                identifier="z-1",
                aliases=frozenset({"z-1"}),
            ),
            paths=(sources_directory / "b.gpkg", sources_directory / "a.gpkg"),
        ),
        peri_scribe.models.FireSources(
            fire=peri_scribe.models.Fire(
                name="Alpha",
                status=tests.helpers.factories.peri_scribe.models.ACTIVE,
            ),
            paths=(sources_directory / "one.gpkg",),
        ),
    ]
    assert peri_scribe.fires.index.fire_index_entries(sources, sources_directory) == [
        {
            "name": "Alpha",
            "status": "active",
            "identifier": None,
            "aliases": [],
            "complex": None,
            "paths": ["one.gpkg"],
        },
        {
            "name": "zulu",
            "status": "inactive",
            "identifier": "z-1",
            "aliases": ["z-1"],
            "complex": None,
            "paths": ["a.gpkg", "b.gpkg"],
        },
    ]


def test_fire_document_describes_complex_membership() -> None:
    child = peri_scribe.models.Fire(
        name="Crosswhite",
        status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        identifier="child-id",
        aliases=frozenset({"child-id"}),
    )
    peri_scribe.models.FireComplex(
        name="ROWE CREEK COMPLEX",
        identifier="parent-id",
        fires=frozenset({child}),
    )
    assert peri_scribe.fires.index.fire_document(child) == {
        "name": "Crosswhite",
        "status": "active",
        "identifier": "child-id",
        "aliases": ["child-id"],
        "complex": {"name": "ROWE CREEK COMPLEX", "identifier": "parent-id"},
    }


def test_index_fire_sources_writes_index_file(
    monkeypatch: pytest.MonkeyPatch,
    stub_fire_reader: tests.helpers.doubles.peri_scribe.fires.sources.StubFireReader,
) -> None:
    year_directory = pathlib.Path("/index/2026")
    monkeypatch.setattr(
        peri_scribe.fires.generation,
        "source_key",
        lambda _year: "in-memory sources",
    )
    stub_fire_reader({
        pathlib.Path("/index/2026/sources/one.gpkg"): [
            tests.helpers.factories.peri_scribe.models.fire_record(
                "Park Fire",
                tests.helpers.factories.peri_scribe.models.ACTIVE,
            ),
        ],
    })
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        lambda _record_groups, _base_dir: {},
    )
    writes: list[tuple[pathlib.Path, peri_scribe.models.FireIndex]] = []
    monkeypatch.setattr(
        peri_scribe.output,
        "write_document",
        lambda path, document: writes.append((path, document)),
    )
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *_args, **_kwargs: None)
    peri_scribe.fires.index.index_fire_sources(year_directory)
    assert writes[0][0] == pathlib.Path("/index/2026/sources/fires.json")
    assert writes[0][1].model_dump() == {
        "version": peri_scribe.fires.index.FIRE_INDEX_VERSION,
        "fires": [
            {
                "name": "Park Fire",
                "status": "active",
                "identifier": None,
                "aliases": [],
                "complex": None,
                "classification": None,
                "paths": ["one.gpkg"],
            },
        ],
    }


def test_fire_index_document_wraps_entries_with_version_and_fires_last() -> None:
    entries: list[dict[str, object]] = [
        {
            "name": "Park Fire",
            "status": "active",
            "identifier": None,
            "aliases": [],
            "complex": None,
            "classification": None,
            "paths": ["one.gpkg"],
        },
    ]
    index = peri_scribe.fires.index.fire_index_document(entries)
    document = index.model_dump()
    assert list(document) == ["version", "fires"]
    assert document["version"] == peri_scribe.fires.index.FIRE_INDEX_VERSION
    assert document["fires"] == entries


def test_fire_index_document_rejects_invalid_entry() -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fires.index.fire_index_document([
            {"name": "Park Fire", "status": "exploded", "paths": []},
        ])


def test_load_fire_index_reads_existing_index(monkeypatch: pytest.MonkeyPatch) -> None:
    year_directory = pathlib.Path("/index/2026")
    document = {
        "version": peri_scribe.fires.index.FIRE_INDEX_VERSION,
        "fires": [
            {
                "name": "Park Fire",
                "status": "active",
                "identifier": None,
                "aliases": [],
                "complex": None,
                "classification": None,
                "paths": ["one.gpkg"],
            },
        ],
    }
    monkeypatch.setattr(
        peri_scribe.fires.index,
        "index_fire_sources",
        lambda _year_directory: pytest.fail("index built for existing file"),
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_args, **_kwargs: json.dumps(document),
    )
    index = peri_scribe.fires.index.load_fire_index(year_directory)
    assert index.model_dump() == document


def test_load_fire_index_builds_index_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = pathlib.Path("/index/2026")
    document = {"version": peri_scribe.fires.index.FIRE_INDEX_VERSION, "fires": []}
    built: list[pathlib.Path] = []
    monkeypatch.setattr(peri_scribe.fires.index, "index_fire_sources", built.append)
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_args, **_kwargs: json.dumps(document),
    )
    index = peri_scribe.fires.index.load_fire_index(year_directory)
    assert built == [year_directory]
    assert index.model_dump() == document


def test_load_fire_index_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        pathlib.Path,
        "read_text",
        lambda _self, *_args, **_kwargs: "not json",
    )
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.fires.index.load_fire_index(pathlib.Path("/index/2026"))


def test_fire_sources_document_includes_classification() -> None:
    sources_directory = pathlib.Path("/index/2026/sources")
    source = peri_scribe.models.FireSources(
        fire=peri_scribe.models.Fire(
            name="Park Fire",
            status=tests.helpers.factories.peri_scribe.models.ACTIVE,
        ),
        paths=(sources_directory / "one.gpkg",),
    )
    classification = peri_scribe.models.FireClassification(
        classification=(
            peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
        ),
        outside_area_fraction=0.0,
        inside_area_fraction=1.0,
        signals=[peri_scribe.models.BorderSignal.GEOMETRY_NEAR],
    )
    document = peri_scribe.fires.index.fire_sources_document(
        source,
        sources_directory,
        classification,
    )
    assert document["classification"] == classification.model_dump(mode="json")
