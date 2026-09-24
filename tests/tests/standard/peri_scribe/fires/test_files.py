"""Incremental histories agree with complete rebuilds after source changes."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import pytest
import shapely

import peri_scribe.execution
import peri_scribe.fires.classification
import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.generation
import peri_scribe.fires.history
import peri_scribe.fires.index
import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.perimeters.versions
import peri_scribe.preparation
import tests.helpers.assertions.peri_scribe.fires.files
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fires.files
import tests.helpers.factories.peri_scribe.models
import tests.helpers.factories.time


if typing.TYPE_CHECKING:
    import spatial_data.layers


@pytest.mark.parametrize("unconditional", [False, True])
def test_write_history_of_full_geography_matches_standalone_with_shared_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    *,
    unconditional: bool,
) -> None:
    peri_scribe.fires.differential.write_history_of_differential_geography(
        tmp_path,
        unconditional=True,
    )
    expected = peri_scribe.fires.derived_layers.read_derived_layers(
        tmp_path,
        tolerate_missing=False,
    )

    with peri_scribe.execution.sharing():
        peri_scribe.fires.index.index_fire_sources(tmp_path)
        for module, function in (
            (peri_scribe.fires.sources, "read_fire_sources"),
            (peri_scribe.fires.sources, "group_fire_sources"),
            (peri_scribe.fires.classification, "classify_fire_sources"),
        ):
            monkeypatch.setattr(
                module,
                function,
                tests.helpers.doubles.errors.raising_stub(
                    AssertionError("Repeated source preparation"),
                ),
            )
        peri_scribe.fires.differential.write_history_of_differential_geography(
            tmp_path,
            unconditional=unconditional,
        )
        actual = peri_scribe.fires.derived_layers.read_derived_layers(
            tmp_path,
            tolerate_missing=False,
        )

    tests.helpers.assertions.peri_scribe.fires.files.assert_histories_equal(
        actual,
        expected,
    )


def test_write_history_of_full_geography_reuses_unchanged_fires(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    peri_scribe.fires.differential.write_history_of_differential_geography(tmp_path)
    first = peri_scribe.fires.derived_layers.read_derived_layers(
        tmp_path,
        tolerate_missing=False,
    )

    unexpected = (
        tests.helpers.doubles.peri_scribe.fires.files.reject_history_reconstruction
    )

    monkeypatch.setattr(peri_scribe.fires.history, "history_rows_for_fire", unexpected)
    monkeypatch.setattr(
        peri_scribe.perimeters.versions,
        "source_observation_from_row",
        unexpected,
    )
    monkeypatch.setattr(
        peri_scribe.fires.differential,
        "differential_rows_for_fire",
        unexpected,
    )
    peri_scribe.fires.differential.write_history_of_differential_geography(tmp_path)
    second = peri_scribe.fires.derived_layers.read_derived_layers(
        tmp_path,
        tolerate_missing=False,
    )
    tests.helpers.assertions.peri_scribe.fires.files.assert_histories_equal(
        first,
        second,
    )


def test_write_history_of_full_geography_keeps_unchanged_files_without_reading_sources(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    signature = peri_scribe.fires.reuse.signature_path(path)
    original = (path.read_bytes(), signature.read_bytes(), path.stat().st_mtime_ns)
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Repeated source read"),
        ),
    )

    result = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)

    assert result == path
    assert (
        path.read_bytes(),
        signature.read_bytes(),
        path.stat().st_mtime_ns,
    ) == original


def test_write_history_of_full_geography_unconditional_bypasses_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Required source read"),
        ),
    )

    with pytest.raises(AssertionError, match="Required source read"):
        peri_scribe.fires.files.write_history_of_full_geography(
            tmp_path,
            unconditional=True,
        )


def test_write_history_of_full_geography_rebuilds_a_changed_source_generation(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    monkeypatch.setattr(
        peri_scribe.fires.generation,
        "source_key",
        lambda _directory: "initial generation",
    )
    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    monkeypatch.setattr(
        peri_scribe.fires.generation,
        "source_key",
        lambda _directory: "changed generation",
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Required source read"),
        ),
    )

    with pytest.raises(AssertionError, match="Required source read"):
        peri_scribe.fires.files.write_history_of_full_geography(tmp_path)


def test_write_history_of_full_geography_inherits_forced_rebuild_scope(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    classified_history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Required source read"),
        ),
    )

    with (
        peri_scribe.preparation.scope(tmp_path, unconditional=True),
        pytest.raises(AssertionError, match="Required source read"),
    ):
        peri_scribe.fires.files.write_history_of_full_geography(tmp_path)


def test_write_history_of_full_geography_retries_without_complete_classifications(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
) -> None:
    path = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    signature = peri_scribe.fires.reuse.validated_signature(path)
    assert signature is not None
    assert signature.generation is None
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        tests.helpers.doubles.errors.raising_stub(
            AssertionError("Required source read"),
        ),
    )

    with pytest.raises(AssertionError, match="Required source read"):
        peri_scribe.fires.files.write_history_of_full_geography(tmp_path)


@pytest.mark.parametrize(
    "change",
    ["growth", "correction", "late", "attributes", "removed", "membership"],
)
def test_write_history_of_full_geography_rebuilds_only_affected_fires(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    history_inputs: list[peri_scribe.fires.sources.ReadFireSources],
    change: str,
) -> None:
    peri_scribe.fires.differential.write_history_of_differential_geography(tmp_path)
    read = history_inputs[0]
    rows = list(read.rows)
    paths = list(read.paths)
    if change in {"growth", "correction", "late"}:
        geometry = shapely.box(-120, 40, -119.97, 40.03)
        if change == "correction":
            geometry = shapely.box(-119.995, 40, -119.98, 40.02)
        observation_time = tests.helpers.factories.time.utc(2026, 9, 4, 0)
        if change == "late":
            observation_time = tests.helpers.factories.time.utc(2026, 9, 2, 0)
        rows.append(
            dataclasses.replace(
                rows[-1],
                record=dataclasses.replace(
                    rows[-1].record,
                    geometry=geometry,
                    observed_at=observation_time,
                ),
            ),
        )
        paths.append(paths[-1].with_name("000003,lastEdit=2.gpkg"))
    elif change == "attributes":
        rows[0] = dataclasses.replace(
            rows[0],
            attributes={**rows[0].attributes, "attr_EstimatedCostToDate": 2000.0},
        )
    elif change == "removed":
        rows.pop()
        paths.pop()
    else:
        read = dataclasses.replace(
            read,
            memberships=(
                peri_scribe.models.ComplexMembership(
                    fire_identifier="first",
                    complex_identifier="complex",
                    complex_name="New complex",
                ),
            ),
        )
    history_inputs[0] = dataclasses.replace(read, rows=tuple(rows), paths=tuple(paths))
    calls: list[str] = []
    derive = peri_scribe.fires.history.history_rows_for_fire

    tracked = tests.helpers.doubles.peri_scribe.fires.files.make_history_recorder(
        calls=calls,
        derive=derive,
    )

    monkeypatch.setattr(peri_scribe.fires.history, "history_rows_for_fire", tracked)
    peri_scribe.fires.differential.write_history_of_differential_geography(tmp_path)
    incremental = peri_scribe.fires.derived_layers.read_derived_layers(
        tmp_path,
        tolerate_missing=False,
    )
    assert calls == ["First"]
    calls.clear()
    peri_scribe.fires.differential.write_history_of_differential_geography(
        tmp_path,
        unconditional=True,
    )
    assert set(calls) == {"First", "Second"}
    complete = peri_scribe.fires.derived_layers.read_derived_layers(
        tmp_path,
        tolerate_missing=False,
    )
    tests.helpers.assertions.peri_scribe.fires.files.assert_histories_equal(
        incremental,
        complete,
    )


def test_history_geopackage_path_names_output() -> None:
    assert peri_scribe.fires.files.history_geopackage_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/derived/history_of_full_geography.gpkg")


def test_write_history_of_full_geography_writes_geography_and_incidents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    record_groups = peri_scribe.fires.sources.FireRecordGroups(
        records=(),
        record_paths=(),
        fires=(tests.helpers.factories.peri_scribe.models.fire(),),
        groups=((),),
        complex_identifiers=frozenset(),
    )
    read = peri_scribe.fires.sources.ReadFireSources(rows=(), paths=(), memberships=())
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        lambda _directory: read,
    )
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "group_fire_sources",
        lambda _read: record_groups,
    )
    monkeypatch.setattr(
        peri_scribe.fires.classification,
        "classify_fire_sources",
        lambda *_args: {},
    )
    written: list[tuple[pathlib.Path, list[spatial_data.layers.LayerData]]] = []
    monkeypatch.setattr(
        peri_scribe.fires.reuse,
        "write_layers",
        lambda path, layers, **_kwargs: written.append((path, layers)),
    )
    result = peri_scribe.fires.files.write_history_of_full_geography(tmp_path)
    assert result == tmp_path / "derived/history_of_full_geography.gpkg"
    assert len(written) == 1
    _path, layers = written[0]
    assert [layer.name for layer in layers] == [
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
        peri_scribe.fires.files.POINT_LAYER_NAME,
        "incident_history",
    ]
