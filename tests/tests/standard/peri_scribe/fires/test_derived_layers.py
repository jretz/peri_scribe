"""Tests for peri_scribe.fires.derived_layers."""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

import peri_scribe.execution
import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.reuse
import peri_scribe.incidents
import spatial_data.layers
import spatial_data.product_cache
import tests.helpers.doubles.errors
import tests.helpers.factories.geography
import tests.helpers.factories.geometry
import tests.helpers.factories.peri_scribe.fires.scores


def test_read_layer_if_present_returns_empty_without_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: False)
    result = peri_scribe.fires.derived_layers.read_layer_if_present(
        pathlib.Path("/missing.gpkg"),
        "layer",
    )
    assert result.empty


def test_read_layer_if_present_reads_existing_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = tests.helpers.factories.peri_scribe.fires.scores.perimeter_frame(
        [{"fire_name": "Bug"}],
        [tests.helpers.factories.geometry.square(1.0)],
    )
    monkeypatch.setattr(pathlib.Path, "is_file", lambda _self: True)
    monkeypatch.setattr(
        spatial_data.layers,
        "read_layer",
        lambda _path, _layer_name: frame,
    )
    result = peri_scribe.fires.derived_layers.read_layer_if_present(
        pathlib.Path("/present.gpkg"),
        "perimeter_history",
    )
    assert result is frame


def test_read_incident_layer_reads_new_layer(tmp_path: pathlib.Path) -> None:
    frame = tests.helpers.factories.geography.geo_frame(
        {"incident_size": [100.0]},
        [None],
    )
    path = tmp_path / "history.gpkg"
    frame.to_file(path, layer="incident_history", driver="GPKG")
    result = peri_scribe.fires.derived_layers.read_incident_layer(path)
    assert result["incident_size"].tolist() == [100.0]


def test_read_incident_layer_returns_empty_for_geography_only_file(
    tmp_path: pathlib.Path,
) -> None:
    frame = tests.helpers.factories.geography.geo_frame(
        {"area_acres": [100.0]},
        [tests.helpers.factories.geometry.square(0.01)],
    )
    path = tmp_path / "history.gpkg"
    frame.to_file(path, layer="perimeter_history", driver="GPKG")
    assert peri_scribe.fires.derived_layers.read_incident_layer(path).empty


def test_read_derived_layers_shares_only_unchanged_files_in_one_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    frame = tests.helpers.factories.geography.empty_frame()
    monkeypatch.setattr(
        peri_scribe.fires.derived_layers,
        "read_incident_layer",
        lambda _path: frame,
    )
    monkeypatch.setattr(spatial_data.layers, "read_layer", lambda _path, _layer: frame)
    history = peri_scribe.fires.files.history_geopackage_path(tmp_path)
    differential = peri_scribe.fires.differential.differential_geopackage_path(tmp_path)
    history.parent.mkdir(parents=True)
    history.touch()
    differential.touch()
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=True,
        )
        assert (
            peri_scribe.fires.derived_layers.read_derived_layers(
                tmp_path,
                tolerate_missing=False,
            )
            is first
        )
        history.write_bytes(b"changed")
        changed = peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=False,
        )
        assert changed is not first
        assert (
            peri_scribe.fires.derived_layers.read_derived_layers(
                tmp_path,
                tolerate_missing=True,
            )
            is changed
        )
    assert (
        peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=True,
        )
        is not changed
    )


def test_read_derived_layers_missing_cache_cannot_satisfy_strict_read(
    tmp_path: pathlib.Path,
) -> None:
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=True,
        )
        assert first.perimeters.empty
        assert (
            peri_scribe.fires.derived_layers.read_derived_layers(
                tmp_path,
                tolerate_missing=True,
            )
            is first
        )
        with pytest.raises(Exception, match="No such file"):
            peri_scribe.fires.derived_layers.read_derived_layers(
                tmp_path,
                tolerate_missing=False,
            )


@pytest.mark.parametrize("tolerate_missing", [False, True])
def test_read_derived_layers_avoids_eager_indexing_of_normalized_publication_layers(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
    *,
    tolerate_missing: bool,
) -> None:
    history = peri_scribe.fires.files.history_geopackage_path(tmp_path)
    differential = peri_scribe.fires.differential.differential_geopackage_path(tmp_path)
    full_names = (
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        peri_scribe.fires.files.POINT_LAYER_NAME,
        peri_scribe.incidents.LAYER_NAME,
    )
    peri_scribe.fires.reuse.write_layers(
        history,
        [dataclasses.replace(cached_layers[0], name=name) for name in full_names],
    )
    peri_scribe.fires.reuse.write_layers(
        differential,
        [dataclasses.replace(cached_layers[0], name=full_names[0])],
    )
    monkeypatch.setattr(
        spatial_data.product_cache,
        "put",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Eager index write")),
    )
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "validated_signature",
        tests.helpers.doubles.errors.raising_stub(AssertionError("Unneeded hashing")),
    )
    with spatial_data.product_cache.scope(tmp_path / "products.sqlite", "test"):
        layers = peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=tolerate_missing,
        )
    for frame in (
        layers.perimeters,
        layers.points,
        layers.incidents,
        layers.differential_perimeters,
    ):
        assert frame.revision.tolist() == [1, 2]
        assert frame.derivation_key.tolist() == ["first", "second"]
