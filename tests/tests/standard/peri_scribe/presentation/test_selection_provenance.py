"""Reconciled source references preserve identity without relying on geometry."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import peri_scribe.presentation.selection
import tests.helpers.factories.peri_scribe.presentation.selection


@pytest.mark.parametrize("object_id", [7, 7.0, "7", "7.0"])
def test_perimeter_groups_preserves_own_and_superseded_source_references(
    object_id: object,
) -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file="corrected.gpkg",
            source_objectid=object_id,
            superseded_sources=json.dumps([
                "original.gpkg#3",
                "earlier.gpkg#2",
                "original.gpkg#3",
            ]),
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert by_name["Timber"][0].source_references == {
        "corrected.gpkg#7",
        "original.gpkg#3",
        "earlier.gpkg#2",
    }


@pytest.mark.parametrize(
    "object_id",
    [
        None,
        pd.NA,
        float("nan"),
        "NaN",
        "None",
        "",
        "wrong",
        1.5,
        "1.5",
        True,
        "9007199254740993.1",
    ],
)
def test_perimeter_groups_omits_incomplete_source_object_identifiers(
    object_id: object,
) -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file="current.gpkg",
            source_objectid=object_id,
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert not by_name["Timber"][0].source_references


@pytest.mark.parametrize("source_file", [None, pd.NA, float("nan"), 1, "", " "])
def test_perimeter_groups_omits_incomplete_source_filenames(
    source_file: object,
) -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file=source_file,
            source_objectid=7,
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert not by_name["Timber"][0].source_references


@pytest.mark.parametrize(
    "superseded_sources",
    [None, pd.NA, float("nan"), "bad JSON", "null", "{}", '"original.gpkg#3"'],
)
def test_perimeter_groups_retains_own_reference_with_invalid_superseded_sources(
    superseded_sources: object,
) -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file="current.gpkg",
            source_objectid=7,
            superseded_sources=superseded_sources,
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert by_name["Timber"][0].source_references == {"current.gpkg#7"}


def test_perimeter_groups_ignores_incomplete_superseded_references() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            superseded_sources=json.dumps([
                "original.gpkg#3",
                "missing.gpkg#None",
                "missing.gpkg#NaN",
                "missing.gpkg#1.5",
                "missing.gpkg#",
                "#7",
                "missing.gpkg",
                7,
                None,
            ]),
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert by_name["Timber"][0].source_references == {"original.gpkg#3"}


@pytest.mark.parametrize("object_id", [9007199254740993, "9007199254740993"])
def test_perimeter_groups_keeps_neighboring_large_object_identifiers_distinct(
    object_id: object,
) -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file="current.gpkg",
            source_objectid=object_id,
            superseded_sources=json.dumps(["current.gpkg#9007199254740992"]),
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert by_name["Timber"][0].source_references == {
        "current.gpkg#9007199254740993",
        "current.gpkg#9007199254740992",
    }


def test_perimeter_groups_preserves_zero_source_object_identifier() -> None:
    frame = (
        tests.helpers.factories.peri_scribe.presentation.selection.perimeter_history(
            source_file="current.gpkg",
            source_objectid=0,
        )
    )
    _, by_name = peri_scribe.presentation.selection.perimeter_groups(frame)
    assert by_name["Timber"][0].source_references == {"current.gpkg#0"}
