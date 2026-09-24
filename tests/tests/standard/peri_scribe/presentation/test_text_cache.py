"""Stable descriptions must remain exact while current score explanations change."""

from __future__ import annotations

import pathlib

import pytest

import peri_scribe.areas
import peri_scribe.presentation.prepared_cache
import peri_scribe.presentation.text
import spatial_data.product_cache
import tests.helpers.doubles.peri_scribe.presentation.prepared_cache
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.fire_data


def test_fire_description_reuses_stable_facts_and_attaches_the_current_note(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    history_factory = tests.helpers.factories.peri_scribe.presentation.fire_data
    perimeters = history_factory.description_perimeter_frame()
    points = history_factory.description_point_frame()
    history = peri_scribe.areas.prepare_history(perimeters, points)
    expected = peri_scribe.presentation.text.fire_description(
        entry,
        perimeters,
        points,
        "Current explanation",
        history=history,
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
            "Old explanation",
            history=history,
        )
    monkeypatch.setattr(
        peri_scribe.presentation.text,
        "build_fire_description",
        lambda *_args, **_kwargs: pytest.fail("Unchanged description was rebuilt"),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
            "Current explanation",
            history=history,
        )
    assert actual == expected


@pytest.mark.parametrize("change", ["entry", "last_row", "history"])
def test_fire_description_invalidates_changed_evidence(
    tmp_path: pathlib.Path,
    change: str,
) -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    history_factory = tests.helpers.factories.peri_scribe.presentation.fire_data
    points = history_factory.description_point_frame()
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        first = peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
        )
    match change:
        case "entry":
            entry.identifier = "changed"
        case "last_row":
            points.loc[points.index[-1], "discovery_time"] = "2026-01-01T00:00:00Z"
        case _:
            points.loc[points.index[0], "incident_size"] = 12345.0
    expected = peri_scribe.presentation.text.fire_description(entry, perimeters, points)
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
        )
    assert actual == expected
    if change != "history":
        assert actual != first


@pytest.mark.parametrize("failure", ["source", "payload", "write"])
def test_fire_description_works_when_cached_facts_are_unavailable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
        "Bug",
        "active",
        identifier="id-bug",
    )
    perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([])
    history_factory = tests.helpers.factories.peri_scribe.presentation.fire_data
    points = history_factory.description_point_frame()
    expected = peri_scribe.presentation.text.fire_description(entry, perimeters, points)
    match failure:
        case "source":
            points["unused"] = [object()] * len(points)
        case "payload":
            monkeypatch.setattr(
                spatial_data.product_cache,
                "get",
                lambda *_args: b"bad",
            )
        case _:
            monkeypatch.setattr(
                peri_scribe.presentation.prepared_cache,
                "description_bytes",
                tests.helpers.doubles.peri_scribe.presentation.prepared_cache.reject_serialization,
            )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        actual = peri_scribe.presentation.text.fire_description(
            entry,
            perimeters,
            points,
        )
    assert actual == expected
