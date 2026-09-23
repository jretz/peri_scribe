"""Identifier enrichment preserves proven mapping history without merging namesakes."""

import dataclasses
import datetime
import json
import pathlib

import pytest
import shapely
import time_machine

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


@pytest.mark.parametrize("legacy_state", [False, True])
def test_prepare_updates_keeps_name_only_history_after_first_identifier(
    tmp_path: pathlib.Path,
    *,
    legacy_state: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
    )
    if legacy_state:
        path = peri_scribe.fire_updates.state_path(tmp_path)
        state = json.loads(path.read_text())
        state.pop("aliases")
        path.write_text(json.dumps(state))

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)

    assert prepared.records == ()
    peri_scribe.fire_updates.write_updates(tmp_path, prepared)
    assert len(peri_scribe.updates.read_entries(tmp_path)) == 1


def test_write_updates_preserves_acreage_when_first_identifier_arrives_with_growth(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    with time_machine.travel(now, tick=False):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
        )
    changed = dataclasses.replace(
        fire,
        perimeters=(
            *fire.perimeters,
            dataclasses.replace(
                fire.perimeters[-1],
                observation_time=now,
                area=1500 * units.acres,
            ),
        ),
    )
    later = now + datetime.timedelta(minutes=5)
    with time_machine.travel(later, tick=False):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, [changed], scores),
        )
        repeated = peri_scribe.fire_updates.prepare_updates(tmp_path, [changed], scores)
    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        later,
    )

    assert [entry.mapped_area.value for entry in snapshot.updates] == [1234.5, 1500]
    assert {entry.identifier for entry in snapshot.updates} == {None}
    assert snapshot.updates[-1].previous_mapped_area == peri_scribe.updates.Acreage(
        value=1234.5,
    )
    assert repeated.records == ()


@pytest.mark.parametrize("legacy_log", [False, True])
def test_write_updates_preserves_acreage_after_identifier_enrichment_and_rename(
    tmp_path: pathlib.Path,
    *,
    legacy_log: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    renamed = dataclasses.replace(
        fire,
        name="Timber Complex",
        perimeters=(
            *fire.perimeters,
            dataclasses.replace(
                fire.perimeters[-1],
                observation_time=now,
                area=1500 * units.acres,
            ),
        ),
    )
    for offset, current in enumerate((original, fire, renamed)):
        with time_machine.travel(now + datetime.timedelta(minutes=offset), tick=False):
            peri_scribe.fire_updates.write_updates(
                tmp_path,
                peri_scribe.fire_updates.prepare_updates(tmp_path, [current], scores),
            )
        if legacy_log and offset == 0:
            path = tmp_path / "logs" / "2026-09-fire-updates.jsonl"
            entry = json.loads(path.read_text())
            entry.pop("log_identity", None)
            path.write_text(json.dumps(entry) + "\n")

    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        now + datetime.timedelta(minutes=2),
    )

    assert [entry.name for entry in snapshot.updates] == ["Timber", "Timber Complex"]
    update = snapshot.updates[-1]
    assert update.previous_mapped_area == peri_scribe.updates.Acreage(value=1234.5)
    change = update.mapped_area.quantity() - update.previous_mapped_area.quantity()
    assert change.m_as("acres") == pytest.approx(265.5)


@pytest.mark.parametrize("same_perimeter", [False, True])
@pytest.mark.parametrize("reverse_order", [False, True])
def test_prepare_updates_requires_unique_evidence_to_claim_name_only_history(
    tmp_path: pathlib.Path,
    *,
    same_perimeter: bool,
    reverse_order: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
    )
    other = dataclasses.replace(
        fire,
        identifiers=frozenset({"2026-other"}),
        perimeters=(
            dataclasses.replace(
                fire.perimeters[-1],
                geometry=(
                    fire.perimeters[-1].geometry
                    if same_perimeter
                    else shapely.box(-122, 37, -121.9, 37.1)
                ),
            ),
        ),
    )
    fires = [other, fire] if reverse_order else [fire, other]

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, fires, scores)

    expected = {"2026-other"}
    if same_perimeter:
        expected.update(fire.identifiers)
    assert {entry["identifier"] for entry in prepared.records} == expected


@pytest.mark.parametrize("reverse_order", [False, True])
def test_prepare_updates_does_not_take_history_from_a_current_name_only_fire(
    tmp_path: pathlib.Path,
    *,
    reverse_order: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
    )
    fires = [fire, original] if reverse_order else [original, fire]

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, fires, scores)

    assert {entry["identifier"] for entry in prepared.records} == set(fire.identifiers)


def test_prepare_updates_does_not_reassign_an_already_identified_name_only_history(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    for current in (original, fire):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, [current], scores),
        )
    other = dataclasses.replace(fire, identifiers=frozenset({"2026-other"}))

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [other], scores)

    assert {entry["identifier"] for entry in prepared.records} == {"2026-other"}


def test_prepare_updates_ignores_empty_shapes_when_matching_name_only_history(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, identifiers=frozenset())
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
    )
    enriched = dataclasses.replace(
        fire,
        perimeters=(
            dataclasses.replace(fire.perimeters[0], geometry=shapely.Polygon()),
            *fire.perimeters,
        ),
    )

    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [enriched], scores)

    assert prepared.records == ()
