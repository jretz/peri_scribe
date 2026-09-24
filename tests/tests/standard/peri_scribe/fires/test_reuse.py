"""Cache identity includes every dependency and output publication is recoverable."""

import dataclasses
import importlib.metadata
import json
import pathlib
import platform
import sys

import pyproj
import pytest
import shapely

import peri_scribe.execution
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.perimeters.cleaning
import peri_scribe.sources.administrative_boundaries
import spatial_data.layers
import tests.helpers.doubles.peri_scribe.fires.reuse
import tests.helpers.peri_scribe.fires.reuse


def test_generation_matches_authenticates_complete_output(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="generation")

    assert peri_scribe.fires.reuse.generation_matches(
        path,
        "generation",
        ("perimeters",),
    )


@pytest.mark.parametrize(
    "damage",
    ["output", "metadata", "signature", "version", "layers", "checksum", "generation"],
)
def test_generation_matches_rejects_incomplete_or_mismatched_outputs(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
    damage: str,
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="generation")
    metadata = peri_scribe.fires.reuse.signature_path(path)
    if damage == "output":
        path.unlink()
    elif damage == "metadata":
        metadata.unlink()
    elif damage == "signature":
        metadata.write_text("invalid")
    else:
        document = json.loads(metadata.read_text())
        document[damage] = (
            -1 if damage == "version" else [] if damage == "layers" else "x"
        )
        metadata.write_text(json.dumps(document))

    assert not peri_scribe.fires.reuse.generation_matches(
        path,
        "generation",
        ("perimeters",),
    )


def test_read_rows_round_trips_complete_output(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    cached = peri_scribe.fires.reuse.read_rows(path, ("perimeters",))
    assert (
        cached["perimeters"]["first"][0]["geometry"]
        == cached_layers[0].dataframe.geometry.iloc[0]
    )
    assert (
        cached["perimeters"]["second"][0]["revision"]
        == cached_layers[0].dataframe.revision.iloc[1]
    )


def test_read_rows_preserves_group_and_row_order_while_excluding_missing_keys(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    frame = cached_layers[0].dataframe.iloc[[1, 0, 1, 0, 0]].reset_index(drop=True)
    frame["derivation_key"] = ["second", None, "first", "second", "first"]
    frame["revision"] = [10, 20, 30, 40, 50]
    peri_scribe.fires.reuse.write_layers(
        path,
        [dataclasses.replace(cached_layers[0], dataframe=frame)],
    )

    cached = peri_scribe.fires.reuse.read_rows(path, ("perimeters",))["perimeters"]
    rows = frame.to_dict("records")

    assert list(cached) == ["second", "first"]
    assert cached == {"second": [rows[0], rows[3]], "first": [rows[2], rows[4]]}


def test_read_rows_preserves_empty_layers_alongside_populated_history(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    empty_layer = dataclasses.replace(
        cached_layers[0],
        name="empty",
        dataframe=cached_layers[0].dataframe.iloc[:0].drop(columns="derivation_key"),
    )
    peri_scribe.fires.reuse.write_layers(path, [empty_layer, *cached_layers])

    cached = peri_scribe.fires.reuse.read_rows(path, ("empty", "perimeters"))

    records = cached_layers[0].dataframe.to_dict("records")
    assert cached == {
        "empty": {},
        "perimeters": {"first": [records[0]], "second": [records[1]]},
    }


@pytest.mark.parametrize(
    "damage",
    ["missing", "signature", "checksum", "schema", "layer", "unconditional"],
)
def test_read_rows_recomputes_unusable_results(
    tmp_path: pathlib.Path,
    cached_layers: list[spatial_data.layers.LayerData],
    damage: str,
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    metadata = peri_scribe.fires.reuse.signature_path(path)
    if damage == "missing":
        path.unlink()
    elif damage == "signature":
        metadata.write_text("broken")
    elif damage == "checksum":
        path.write_bytes(b"interrupted")
    elif damage == "schema":
        signature = peri_scribe.fires.reuse.Signature(
            version=-1,
            checksum=peri_scribe.fires.reuse.file_digest(path),
        )
        metadata.write_text(signature.model_dump_json())
    elif damage == "layer":
        cached_layers[0].dataframe.drop(columns="derivation_key", inplace=True)
        peri_scribe.fires.reuse.write_layers(path, cached_layers)
    assert (
        peri_scribe.fires.reuse.read_rows(
            path,
            ("perimeters",),
            unconditional=damage == "unconditional",
        )
        == {}
    )


def test_write_layers_preserves_old_output_when_generation_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="original")
    original = path.read_bytes()

    fail = tests.helpers.doubles.peri_scribe.fires.reuse.write_partial_output_and_fail

    monkeypatch.setattr(spatial_data.layers, "write_geopackage", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="changed")
    assert path.read_bytes() == original
    assert peri_scribe.fires.reuse.read_rows(path, ("perimeters",))
    assert peri_scribe.fires.reuse.generation_matches(path, "original", ("perimeters",))
    assert not peri_scribe.fires.reuse.generation_matches(
        path,
        "changed",
        ("perimeters",),
    )


def test_derivation_context_tracks_boundary_and_configuration(
    tmp_path: pathlib.Path,
) -> None:
    first = peri_scribe.fires.reuse.derivation_context(tmp_path)
    boundary = peri_scribe.sources.administrative_boundaries.output_geopackage_path(
        tmp_path,
    )
    boundary.parent.mkdir(parents=True)
    boundary.write_bytes(b"boundary")
    second = peri_scribe.fires.reuse.derivation_context(tmp_path)
    assert first != second
    boundary.write_bytes(b"edited boundary")
    assert second != peri_scribe.fires.reuse.derivation_context(tmp_path)


def test_data_digest_ignores_dictionary_insertion_order() -> None:
    assert peri_scribe.fires.reuse.data_digest({
        "a": 1,
        "b": 2,
    }) == peri_scribe.fires.reuse.data_digest({"b": 2, "a": 1})


def test_shared_fire_keys_retains_fingerprints_within_execution(
    source_rows: peri_scribe.fires.sources.ReadFireSources,
) -> None:
    groups = peri_scribe.fires.sources.group_fire_sources(source_rows)
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.reuse.shared_fire_keys(
            source_rows,
            groups,
            pathlib.Path("sources"),
            "context",
        )
        second = peri_scribe.fires.reuse.shared_fire_keys(
            source_rows,
            groups,
            pathlib.Path("sources"),
            "context",
        )

    assert second is first


@pytest.mark.parametrize("change", ["read", "groups", "context"])
def test_shared_fire_keys_rechecks_new_evidence_and_context(
    source_rows: peri_scribe.fires.sources.ReadFireSources,
    change: str,
) -> None:
    groups = peri_scribe.fires.sources.group_fire_sources(source_rows)
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.reuse.shared_fire_keys(
            source_rows,
            groups,
            pathlib.Path("sources"),
            "context",
        )
        second = peri_scribe.fires.reuse.shared_fire_keys(
            dataclasses.replace(source_rows) if change == "read" else source_rows,
            dataclasses.replace(groups) if change == "groups" else groups,
            pathlib.Path("sources"),
            "changed" if change == "context" else "context",
        )

    assert second is not first
    assert (second == first) == (change != "context")


def test_shared_fire_keys_releases_fingerprints_after_execution(
    source_rows: peri_scribe.fires.sources.ReadFireSources,
) -> None:
    groups = peri_scribe.fires.sources.group_fire_sources(source_rows)
    with peri_scribe.execution.sharing():
        first = peri_scribe.fires.reuse.shared_fire_keys(
            source_rows,
            groups,
            pathlib.Path("sources"),
            "context",
        )
    second = peri_scribe.fires.reuse.shared_fire_keys(
        source_rows,
        groups,
        pathlib.Path("sources"),
        "context",
    )

    assert second is not first
    assert second == first


@pytest.mark.parametrize("dependency", ["geos", "proj", "python", "platform"])
def test_derivation_context_tracks_native_runtime(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    first = peri_scribe.fires.reuse.derivation_context(tmp_path)
    if dependency == "geos":
        monkeypatch.setattr(shapely, "geos_version_string", "changed")
    elif dependency == "proj":
        monkeypatch.setattr(pyproj, "proj_version_str", "changed")
    elif dependency == "python":
        monkeypatch.setattr(sys, "version", "changed")
    else:
        monkeypatch.setattr(platform, "platform", lambda: "changed")

    assert peri_scribe.fires.reuse.derivation_context(tmp_path) != first


@pytest.mark.parametrize("dependency", ["pandas", "numpy", "pydantic"])
def test_derivation_context_tracks_data_library_versions(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    dependency: str,
) -> None:
    first = peri_scribe.fires.reuse.derivation_context(tmp_path)
    version = importlib.metadata.version
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: "changed" if name == dependency else version(name),
    )

    assert peri_scribe.fires.reuse.derivation_context(tmp_path) != first


def test_derivation_context_changes_when_settings_change(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = peri_scribe.fires.reuse.derivation_context(tmp_path)
    config = peri_scribe.perimeters.cleaning.DEFAULT_CLEANING_CONFIG
    monkeypatch.setattr(
        peri_scribe.perimeters.cleaning,
        "DEFAULT_CLEANING_CONFIG",
        dataclasses.replace(config, maximum_deviation=config.maximum_deviation * 2),
    )
    assert peri_scribe.fires.reuse.derivation_context(tmp_path) != first


def test_write_layers_does_not_trust_unpublished_metadata(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_layers: list[spatial_data.layers.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="original")
    replace = pathlib.Path.replace
    cached_layers[0].dataframe["revision"] = 3

    interrupted = (
        tests.helpers.doubles.peri_scribe.fires.reuse.make_interrupted_replacement(
            path=path,
            replace=replace,
        )
    )

    monkeypatch.setattr(pathlib.Path, "replace", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        peri_scribe.fires.reuse.write_layers(path, cached_layers, generation="changed")
    assert peri_scribe.fires.reuse.read_rows(path, ("perimeters",)) == {}
    assert not peri_scribe.fires.reuse.generation_matches(
        path,
        "original",
        ("perimeters",),
    )
    assert not peri_scribe.fires.reuse.generation_matches(
        path,
        "changed",
        ("perimeters",),
    )


@pytest.mark.parametrize(
    "change",
    [
        "attributes",
        "geometry",
        "order",
        "removed",
        "provenance",
        "context",
        "membership",
    ],
)
def test_fire_keys_invalidate_changed_dependencies(
    source_rows: peri_scribe.fires.sources.ReadFireSources,
    change: str,
) -> None:
    first = tests.helpers.peri_scribe.fires.reuse.source_key(source_rows)
    rows = list(source_rows.rows)
    if change == "attributes":
        rows[0] = dataclasses.replace(rows[0], attributes={"revision": "corrected"})
    elif change == "geometry":
        rows[0] = dataclasses.replace(
            rows[0],
            record=dataclasses.replace(
                rows[0].record,
                geometry=shapely.box(0, 0, 2, 2),
            ),
        )
    elif change == "order":
        rows.reverse()
    elif change == "removed":
        rows.pop()
        source_rows = dataclasses.replace(source_rows, paths=source_rows.paths[:-1])
    elif change == "provenance":
        source_rows = dataclasses.replace(
            source_rows,
            paths=tuple(
                path.with_name("new,lastEdit=2.gpkg") for path in source_rows.paths
            ),
        )
    elif change == "membership":
        source_rows = dataclasses.replace(
            source_rows,
            memberships=(
                peri_scribe.models.ComplexMembership(
                    fire_identifier="example",
                    complex_identifier="complex",
                    complex_name="Complex",
                ),
            ),
        )
    changed = dataclasses.replace(source_rows, rows=tuple(rows))
    assert first != tests.helpers.peri_scribe.fires.reuse.source_key(
        changed,
        "changed" if change == "context" else "context",
    )


@pytest.mark.parametrize(
    "package",
    ["peri_scribe", "arcgis_access", "measurement_units", "spatial_data"],
)
def test_derivation_context_tracks_extracted_package_code(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    package: str,
) -> None:
    source_root = tmp_path / "src"
    module_path = source_root / "peri_scribe" / "fires" / "reuse.py"
    monkeypatch.setattr(peri_scribe.fires.reuse, "__file__", str(module_path))
    dependency = source_root / package / "geometry.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("algorithm = 1\n")
    first = peri_scribe.fires.reuse.derivation_context(tmp_path)
    dependency.write_text("algorithm = 2\n")
    assert peri_scribe.fires.reuse.derivation_context(tmp_path) != first
