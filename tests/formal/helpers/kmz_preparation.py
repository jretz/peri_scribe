"""Bind compact KMZ preparation to checked demand, selection, and identity rules."""

from __future__ import annotations

import dataclasses
import enum
import itertools
import json
import pathlib

import geopandas
import pandas as pd
import pandas.testing
import pytest
import shapely

import peri_scribe.areas
import peri_scribe.kml.prepared_inputs
import peri_scribe.models
import peri_scribe.presentation.history_index
import peri_scribe.presentation.selection
import spatial_data.product_cache
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.kml.parsing
from measurement_units import units


class Dependency(enum.IntEnum):
    """Keep concrete cache mutations aligned with the oracle's dependency columns."""

    UNCHANGED = -1
    FULL_GENERATION = 0
    DIFFERENTIAL_GENERATION = 1
    FIRE_INDEX = 2
    MINIMUM_AREA = 3
    AREA_POLICY = 4
    RUNTIME = 5


def selection_text(groups: tuple[tuple[int, ...], ...]) -> str:
    """Transport actual ordered selections without applying demand policy in Python.

    Args:
        groups: Original row selections, including empty and overlapping groups.

    Returns:
        The Lean oracle's position-list representation.
    """
    return ";".join(",".join(map(str, group)) for group in groups)


def check_latest_positions() -> None:
    """Check last-position demand through all short mixtures and overlapping groups."""
    selections = tuple(
        itertools.chain.from_iterable(
            itertools.product(range(4), repeat=count) for count in range(4)
        ),
    )
    cases = (
        (),
        *((selection,) for selection in selections),
        *((first, second) for first, second in itertools.product(selections, repeat=2)),
    )
    expected = tests.formal.helpers.oracle.evaluate(
        ["demands|" + selection_text(groups) for groups in cases],
        executable="oracleKmzPreparation",
    )
    for groups, demanded in zip(cases, expected, strict=True):
        actual = peri_scribe.kml.prepared_inputs.latest_positions(groups)
        assert actual == tuple(sorted(set(demanded)))


def selected_index() -> peri_scribe.models.FireIndex:
    """Exercise exact components, aliases, legacy names, and absent selections.

    Returns:
        Identities whose source selections have distinct and overlapping latest rows.
    """
    entry = tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry
    return tests.helpers.factories.peri_scribe.kml.parsing.fire_index([
        entry("Shared", "active", identifier="other").model_copy(
            update={"component_id": "a"},
        ),
        entry("Shared", "active", identifier="fire").model_copy(
            update={"component_id": "missing"},
        ),
        entry("Shared", "active", identifier="fire", aliases=["alias"]),
        entry("Anonymous", "active"),
        entry("Shared", "active", identifier="other"),
        entry("Shared", "active"),
    ])


def check_projected_values(directory: pathlib.Path) -> None:
    """Read real GeoPackage attributes with holes in FIDs and compare checked demand.

    Args:
        directory: Isolated root for the concrete vector layer.
    """
    path = directory / "projected.gpkg"
    identifiers = ("alias", "fire", None, "other", "fire", None, "excluded")
    names = (
        "Shared",
        "Shared",
        "Anonymous",
        "Shared",
        "Shared",
        "Anonymous",
        "Excluded",
    )
    components = ("a", "a", "b", "c", "a", "b", "d")
    values = tuple(range(101, 108))
    frame = geopandas.GeoDataFrame(
        {
            "fire_identifier": identifiers,
            "fire_name": names,
            "fire_component_id": components,
            "source_attributes": [json.dumps({"value": value}) for value in values],
            "area_acres": [float(value) for value in values],
        },
        geometry=[shapely.Point(-120 + offset / 100, 35) for offset in range(7)],
        crs="EPSG:4326",
        index=pd.Index([3, 7, 12, 40, 48, 82, 101], name="fid"),
    )
    frame.to_file(path, layer="history", driver="GPKG", index=True)
    full = geopandas.read_file(path, layer="history")
    index = selected_index()
    rows = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(full)
    selections = tuple(
        rows.positions_for(
            peri_scribe.presentation.selection.identifiers(entry),
            entry.name,
            entry.component_id,
        )
        for entry in index.fires
    )
    (expected,) = tests.formal.helpers.oracle.evaluate(
        ["projection|" + ",".join(map(str, values)) + "|" + selection_text(selections)],
        executable="oracleKmzPreparation",
    )
    actual = peri_scribe.kml.prepared_inputs.read_projected_layer(
        path,
        "history",
        index,
    )
    assert list(actual.columns) == list(full.columns)
    assert actual["source_attributes"].dtype == full["source_attributes"].dtype
    pandas.testing.assert_frame_equal(
        actual.drop(columns="source_attributes"),
        full.drop(columns="source_attributes"),
    )
    for original, projected, retained in zip(
        full["source_attributes"],
        actual["source_attributes"],
        expected,
        strict=True,
    ):
        if retained:
            assert projected == original
            assert json.loads(projected)["value"] == retained
        else:
            assert pd.isna(projected)


def check_qualifying_histories() -> None:
    """Retain complete qualified evidence at the established 25-acre boundary."""
    cases = ((None, False), (0, False), (24, False), (25, True), (100, True))
    histories = {
        ("id", str(index)): peri_scribe.areas.PreparedHistory(
            updates=(),
            estimates=(),
            latest_area=(index + 100) * units.acres,
            historical_area=None if area is None else area * units.acres,
        )
        for index, (area, _qualified) in enumerate(cases)
    }
    (expected,) = tests.formal.helpers.oracle.evaluate(
        [
            "qualifying|"
            + ";".join(
                f"{index},{index + 100},{int(qualified)}"
                for index, (_area, qualified) in enumerate(cases)
            ),
        ],
        executable="oracleKmzPreparation",
    )
    actual = peri_scribe.kml.prepared_inputs.qualifying_histories(histories)
    retained = []
    for key, history in actual.items():
        assert history.latest_area is not None
        retained.append((int(key[1]), history.latest_area.m_as("acres")))
    assert tuple(retained) == tuple(
        zip(
            expected[::2],
            expected[1::2],
            strict=True,
        ),
    )
    assert all(history == histories[key] for key, history in actual.items())


def check_preparation_identity(directory: pathlib.Path) -> None:
    """Reject changes to every preparation dependency through real product storage.

    Args:
        directory: Isolated persistent product database root.
    """
    index = selected_index()
    identity = ("full-zero", "differential-zero")
    key = peri_scribe.kml.prepared_inputs.preparation_key(identity, index)
    path = directory / "products.sqlite"
    namespace = "formal-kmz-preparation"
    with spatial_data.product_cache.scope(path, "runtime-zero"):
        spatial_data.product_cache.put(namespace, key, b"complete-manifest")
    commands = [
        "identity|0,0,0,0,0,0|"
        + ",".join(str(int(index == changed.value)) for index in range(6))
        for changed in Dependency
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleKmzPreparation",
    )
    for changed, (matching,) in zip(Dependency, expected, strict=True):
        current_identity = identity
        current_index = index.model_copy(deep=True)
        context = "runtime-zero"
        with pytest.MonkeyPatch.context() as monkeypatch:
            if changed is Dependency.FULL_GENERATION:
                current_identity = ("full-one", identity[1])
            elif changed is Dependency.DIFFERENTIAL_GENERATION:
                current_identity = (identity[0], "differential-one")
            elif changed is Dependency.FIRE_INDEX:
                current_index.fires[0].aliases.append("new-alias")
            elif changed is Dependency.MINIMUM_AREA:
                monkeypatch.setattr(
                    peri_scribe.presentation.selection,
                    "MINIMUM_FIRE_AREA",
                    26 * units.acres,
                )
            elif changed is Dependency.AREA_POLICY:
                monkeypatch.setattr(
                    peri_scribe.areas,
                    "DEFAULT_POLICY",
                    dataclasses.replace(
                        peri_scribe.areas.DEFAULT_POLICY,
                        footprint_fraction=0.02,
                    ),
                )
            elif changed is Dependency.RUNTIME:
                context = "runtime-one"
            current_key = peri_scribe.kml.prepared_inputs.preparation_key(
                current_identity,
                current_index,
            )
            with spatial_data.product_cache.scope(path, context):
                found = spatial_data.product_cache.get(namespace, current_key)
            assert (found == b"complete-manifest") == bool(matching)
