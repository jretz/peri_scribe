"""Cache identity includes every dependency and output publication is recoverable."""

import dataclasses
import pathlib

import geopandas
import pytest
import shapely

import peri_scribe.fires.reuse
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.output
import peri_scribe.perimeters.cleaning
import peri_scribe.sources.administrative_boundaries
import tests.factories


@pytest.fixture
def cached_layers() -> list[peri_scribe.models.LayerData]:
    """Supply an isolated cache payload.

    Returns:
        Small independent histories with stable derivation keys.
    """
    return [
        peri_scribe.models.LayerData(
            name="perimeters",
            dataframe=geopandas.GeoDataFrame(
                {"derivation_key": ["first", "second"], "revision": [1, 2]},
                geometry=[shapely.box(0, 0, 1, 1), shapely.box(2, 2, 3, 3)],
                crs=4326,
            ),
        ),
    ]


def test_read_rows_round_trips_complete_output(
    tmp_path: pathlib.Path,
    cached_layers: list[peri_scribe.models.LayerData],
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


@pytest.mark.parametrize(
    "damage",
    ["missing", "signature", "checksum", "schema", "layer", "unconditional"],
)
def test_read_rows_recomputes_unusable_results(
    tmp_path: pathlib.Path,
    cached_layers: list[peri_scribe.models.LayerData],
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
    cached_layers: list[peri_scribe.models.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    original = path.read_bytes()

    def fail(path: pathlib.Path, _layers: list[peri_scribe.models.LayerData]) -> None:
        path.write_bytes(b"partial")
        message = "interrupted"
        raise RuntimeError(message)

    monkeypatch.setattr(peri_scribe.output, "write_geopackage", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        peri_scribe.fires.reuse.write_layers(path, cached_layers)
    assert path.read_bytes() == original
    assert peri_scribe.fires.reuse.read_rows(path, ("perimeters",))


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


@pytest.fixture
def source_rows() -> peri_scribe.fires.sources.ReadFireSources:
    """Supply observations whose dependencies can change independently.

    Returns:
        Repeated shapes and a missing geometry under one fire identity.
    """
    geometry = shapely.box(0, 0, 1, 1)
    return peri_scribe.fires.sources.ReadFireSources(
        rows=tuple(
            peri_scribe.geo.package.FireRowRecord(
                record=tests.factories.fire_record(
                    "Example",
                    tests.factories.ACTIVE,
                    {"example"},
                    geometry=shape,
                ),
                source_name="CA_Perimeters_NIFC_FIRIS_public_view_0",
                object_id=1,
                attributes={"revision": index},
            )
            for index, shape in enumerate([geometry, geometry, None])
        ),
        paths=tuple(
            pathlib.Path(f"sources/feed/00000{index},lastEdit=1.gpkg")
            for index in range(3)
        ),
        memberships=(),
    )


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
    cached_layers: list[peri_scribe.models.LayerData],
) -> None:
    path = tmp_path / "history.gpkg"
    peri_scribe.fires.reuse.write_layers(path, cached_layers)
    replace = pathlib.Path.replace
    cached_layers[0].dataframe["revision"] = 3

    def interrupted(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        if target == peri_scribe.fires.reuse.signature_path(path):
            message = "interrupted metadata publication"
            raise OSError(message)
        return replace(source, target)

    monkeypatch.setattr(pathlib.Path, "replace", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        peri_scribe.fires.reuse.write_layers(path, cached_layers)
    assert peri_scribe.fires.reuse.read_rows(path, ("perimeters",)) == {}


def source_key(
    read: peri_scribe.fires.sources.ReadFireSources,
    context: str = "context",
) -> str:
    groups = peri_scribe.fires.sources.group_fire_sources(read)
    return next(
        iter(
            peri_scribe.fires.reuse.fire_keys(
                read,
                groups,
                pathlib.Path("sources"),
                context,
            ).values(),
        ),
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
    first = source_key(source_rows)
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
    assert first != source_key(changed, "changed" if change == "context" else "context")
