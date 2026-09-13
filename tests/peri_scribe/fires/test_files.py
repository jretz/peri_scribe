"""Incremental histories agree with complete rebuilds after source changes."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import geopandas.testing
import pytest
import shapely

import peri_scribe.fires.derived_layers
import peri_scribe.fires.differential
import peri_scribe.fires.history
import peri_scribe.fires.sources
import peri_scribe.geo.package
import peri_scribe.models
import peri_scribe.perimeters.versions
import tests.factories


@pytest.fixture
def history_inputs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> list[peri_scribe.fires.sources.ReadFireSources]:
    """Exercise real derivation and file I/O with isolated source-reader inputs.

    Args:
        tmp_path: The isolated year directory for source paths and derived output.
        monkeypatch: The fixture used to replace the source reader.

    Returns:
        A replaceable source read for two independently changing fires.
    """
    feed = "CA_Perimeters_NIFC_FIRIS_public_view_0"
    rows = tuple(
        peri_scribe.geo.package.FireRowRecord(
            record=tests.factories.fire_record(
                name,
                tests.factories.ACTIVE,
                {name.casefold()},
                geometry=geometry,
                observed_at=tests.factories.utc(2026, 9, 1 + index, 0),
            ),
            source_name=feed,
            object_id=index,
            attributes={
                "area_acres": 100.0,
                "attr_ModifiedOnDateTime_dt": tests.factories.utc(
                    2026,
                    9,
                    1 + index,
                    0,
                ),
                "attr_IncidentSize": 100.0,
                "attr_EstimatedCostToDate": 1000.0,
            },
        )
        for index, (name, geometry) in enumerate([
            ("First", shapely.box(-120, 40, -119.99, 40.01)),
            ("Second", shapely.box(-121, 40, -120.99, 40.01)),
            ("First", shapely.box(-120, 40, -119.98, 40.02)),
        ])
    )
    inputs = [
        peri_scribe.fires.sources.ReadFireSources(
            rows=rows,
            paths=tuple(
                tmp_path / "sources" / feed / "000___" / f"{index:06d},lastEdit=1.gpkg"
                for index in range(len(rows))
            ),
            memberships=(),
        ),
    ]
    monkeypatch.setattr(
        peri_scribe.fires.sources,
        "read_fire_sources",
        lambda _directory: inputs[0],
    )
    return inputs


def assert_histories_equal(
    left: peri_scribe.fires.derived_layers.DerivedLayers,
    right: peri_scribe.fires.derived_layers.DerivedLayers,
) -> None:
    """Require reused and rebuilt histories to retain the same evidence and geometry.

    Args:
        left: The histories produced by an incremental rebuild.
        right: The independently rebuilt reference histories.
    """
    for name in ("perimeters", "points", "differential_perimeters", "incidents"):
        first = getattr(left, name)
        second = getattr(right, name)
        geopandas.testing.assert_geodataframe_equal(first, second)
        assert list(first.geometry.to_wkb()) == list(second.geometry.to_wkb())


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

    def unexpected(*_args: object, **_kwargs: object) -> typing.Never:
        """Reject source reconstruction when a complete cached history is available.

        Args:
            _args: Unused derivation inputs.
            _kwargs: Unused derivation options.

        Raises:
            AssertionError: When an unchanged fire's evidence is reconstructed.
        """
        message = "An unchanged fire was recomputed"
        raise AssertionError(message)

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
    assert_histories_equal(first, second)


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
        observation_time = tests.factories.utc(2026, 9, 4, 0)
        if change == "late":
            observation_time = tests.factories.utc(2026, 9, 2, 0)
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
            attributes={
                **rows[0].attributes,
                "attr_EstimatedCostToDate": 2000.0,
            },
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

    def tracked(
        fire: peri_scribe.models.Fire,
        group: tuple[int, ...],
        full_rows: list[peri_scribe.geo.package.FireRowRecord],
        full_paths: list[pathlib.Path],
        *,
        sources_directory: pathlib.Path,
        classification: peri_scribe.models.FireClassification | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Observe which fires need reconstruction while preserving real derivation.

        Args:
            fire: The fire being reconstructed.
            group: Its source-record positions.
            full_rows: The source observations for this test.
            full_paths: The corresponding snapshot paths.
            sources_directory: The base for snapshot provenance.
            classification: The selected border classification.

        Returns:
            The derived perimeter and point rows.
        """
        calls.append(fire.name)
        return derive(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classification,
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
    assert_histories_equal(incremental, complete)
