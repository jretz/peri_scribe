"""Mapping corrections keep acreage history when replacement removes old geometry."""

import dataclasses
import datetime
import json
import pathlib

import pytest
import shapely
import time_machine

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.perimeters.versions
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.fire_update_corrections


def test_write_updates_preserves_name_only_identity_after_mapping_revision(
    tmp_path: pathlib.Path,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.fire_update_corrections.observations()
    )
    first = tests.helpers.factories.peri_scribe.fire_update_corrections.summary(
        observations[:1],
    )
    corrected = tests.helpers.factories.peri_scribe.fire_update_corrections.summary(
        observations,
    )
    assert len(first.perimeters) == len(corrected.perimeters) == 1
    assert first.perimeters[0].geometry != corrected.perimeters[0].geometry
    assert first.type_one
    assert corrected.type_one
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    now = datetime.datetime(2026, 9, 23, 18, tzinfo=datetime.UTC)
    for offset, fire in enumerate((first, corrected)):
        publication_time = now + datetime.timedelta(minutes=5 * offset)
        with time_machine.travel(publication_time, tick=False):
            peri_scribe.fire_updates.write_updates(
                tmp_path,
                peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores),
            )
    entries = peri_scribe.updates.read_entries(tmp_path)
    first_entry, corrected_entry = entries
    assert (
        first_entry.log_identity == corrected_entry.log_identity == ("name", "Timber")
    )
    snapshot = peri_scribe.updates.snapshot_from_entries(
        entries,
        now + datetime.timedelta(minutes=5),
    )
    previous_area = first.perimeters[0].measured_area.m_as("acres")
    corrected_area = corrected.perimeters[0].measured_area.m_as("acres")
    update = snapshot.updates[-1]
    assert update.previous_mapped_area is not None
    assert update.previous_mapped_area.value == pytest.approx(previous_area)
    assert update.mapped_area.value == pytest.approx(corrected_area)
    change = update.mapped_area.value - update.previous_mapped_area.value
    assert change == pytest.approx(corrected_area - previous_area)
    assert change < 0
    repeated = peri_scribe.fire_updates.prepare_updates(tmp_path, [corrected], scores)
    assert repeated.records == ()


@pytest.mark.parametrize("same_source_file", [False, True])
def test_prepare_updates_keeps_distant_name_only_mapping_separate(
    tmp_path: pathlib.Path,
    *,
    same_source_file: bool,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.fire_update_corrections.observations()
    )
    original = observations[0]
    distant = dataclasses.replace(
        observations[1],
        geometry=shapely.box(-119.5, 38.2, -119.4, 38.3),
        source_file=original.source_file if same_source_file else "distant.gpkg",
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    first = tests.helpers.factories.peri_scribe.fire_update_corrections.summary([
        original,
    ])
    new_fire = tests.helpers.factories.peri_scribe.fire_update_corrections.summary([
        distant,
    ])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [first], scores),
    )

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [new_fire], scores)

    assert len(prepared.records) == 1
    assert prepared.records[0]["log_identity"] != ["name", "Timber"]


def test_write_updates_acknowledges_new_provenance_without_mapping_notification(
    tmp_path: pathlib.Path,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.fire_update_corrections.observations()
    )
    original = observations[0]
    republished = dataclasses.replace(
        original,
        source_file="republished.gpkg",
        object_id=20,
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    first = tests.helpers.factories.peri_scribe.fire_update_corrections.summary([
        original,
    ])
    first_updates = peri_scribe.fire_updates.prepare_updates(tmp_path, [first], scores)
    peri_scribe.fire_updates.write_updates(tmp_path, first_updates)
    current = tests.helpers.factories.peri_scribe.fire_update_corrections.summary([
        republished,
    ])

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [current], scores)

    assert prepared.records == ()
    peri_scribe.fire_updates.write_updates(tmp_path, prepared)
    state = peri_scribe.fire_updates.State.model_validate_json(
        peri_scribe.fire_updates.state_path(tmp_path).read_text(),
    )
    key = json.dumps(("name", "Timber"))
    assert state.sources[key] == (
        first.perimeters[0].source_references | current.perimeters[0].source_references
    )
    assert state.sources[key] > first_updates.state.sources[key]
    assert len(peri_scribe.updates.read_entries(tmp_path)) == 1


def test_write_updates_seeds_legacy_checkpoint_provenance_before_correction(
    tmp_path: pathlib.Path,
) -> None:
    observations = (
        tests.helpers.factories.peri_scribe.fire_update_corrections.observations()
    )
    first = tests.helpers.factories.peri_scribe.fire_update_corrections.summary(
        observations[:1],
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [first], scores),
    )
    path = peri_scribe.fire_updates.state_path(tmp_path)
    state = json.loads(path.read_text())
    state.pop("sources")
    path.write_text(json.dumps(state))

    repeated = peri_scribe.fire_updates.prepare_updates(tmp_path, [first], scores)
    assert repeated.records == ()
    peri_scribe.fire_updates.write_updates(tmp_path, repeated)
    corrected = tests.helpers.factories.peri_scribe.fire_update_corrections.summary(
        observations,
    )
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [corrected], scores),
    )

    entries = peri_scribe.updates.read_entries(tmp_path)
    first_entry, corrected_entry = entries
    assert first_entry.log_identity == corrected_entry.log_identity
    snapshot = peri_scribe.updates.snapshot_from_entries(
        entries,
        datetime.datetime.now(datetime.UTC),
    )
    update = snapshot.updates[-1]
    assert update.previous_mapped_area is not None
    assert update.previous_mapped_area.value == pytest.approx(
        first.perimeters[0].measured_area.m_as("acres"),
    )
    assert update.mapped_area.value < update.previous_mapped_area.value


def test_write_updates_keeps_correction_identity_through_duplicate_publication(
    tmp_path: pathlib.Path,
) -> None:
    original, correction = (
        tests.helpers.factories.peri_scribe.fire_update_corrections.observations()
    )
    duplicate = dataclasses.replace(
        original,
        snapshot_time=correction.snapshot_time,
        serial_number=original.serial_number + 1,
        source_file="duplicate.gpkg",
    )
    correction = dataclasses.replace(
        correction,
        serial_number=duplicate.serial_number + 1,
    )
    retained = (
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
            original,
            duplicate,
            correction,
        ])
    )
    first = tests.helpers.factories.peri_scribe.fire_update_corrections.summary([
        original,
    ])
    corrected = tests.helpers.factories.peri_scribe.fire_update_corrections.summary(
        retained,
    )
    assert len(corrected.perimeters) == 1
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    for fire in (first, corrected):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores),
        )

    entries = peri_scribe.updates.read_entries(tmp_path)
    first_entry, corrected_entry = entries
    assert first_entry.log_identity == corrected_entry.log_identity
    snapshot = peri_scribe.updates.snapshot_from_entries(
        entries,
        datetime.datetime.now(datetime.UTC),
    )
    update = snapshot.updates[-1]
    assert update.previous_mapped_area is not None
    assert update.previous_mapped_area.value == pytest.approx(
        first.perimeters[0].measured_area.m_as("acres"),
    )
    assert update.mapped_area.value < update.previous_mapped_area.value
