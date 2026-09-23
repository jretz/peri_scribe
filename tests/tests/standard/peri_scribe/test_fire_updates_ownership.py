"""Fire update histories remain distinct through changes in names and identifiers."""

import dataclasses
import datetime
import json
import pathlib

import pytest
import shapely

import peri_scribe.fire_updates
import peri_scribe.models
import peri_scribe.publication
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.fire_updates
import tests.helpers.factories.peri_scribe.fire_updates_ownership
from measurement_units import units


@pytest.mark.parametrize("reverse_order", [False, True])
def test_prepare_updates_keeps_new_namesakes_separate_from_enriched_history(
    tmp_path: pathlib.Path,
    *,
    reverse_order: bool,
) -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    renamed = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_renamed(
            tmp_path,
            now,
        )
    )
    namesake = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.distant_namesake(
            now,
        )
    )
    fires = tests.helpers.factories.peri_scribe.fire_updates_ownership.grouped_fires([
        renamed,
        namesake,
    ])
    assert [current.name for current in fires] == ["Timber", "Timber Complex"]
    assert [bool(current.identifiers) for current in fires] == [False, True]
    if reverse_order:
        fires.reverse()
    later = now + datetime.timedelta(minutes=3)
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    pending = peri_scribe.fire_updates.prepare_updates(tmp_path, fires, scores)
    retry = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        list(reversed(fires)),
        scores,
    )
    assert retry == pending

    prepared = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            fires,
            later,
        )
    )

    assert [entry["name"] for entry in prepared.records] == ["Timber"]
    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        later,
    )
    assert [entry.mapped_area.value for entry in snapshot.updates] == [1234.5, 100]
    assert all(entry.previous_mapped_area is None for entry in snapshot.updates)
    assert snapshot.updates[0].log_identity != snapshot.updates[1].log_identity
    repeated = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            fires,
            later + datetime.timedelta(minutes=1),
        )
    )
    assert repeated.records == ()

    growth_time = later + datetime.timedelta(minutes=2)
    growing = [
        dataclasses.replace(
            current,
            perimeters=(
                *current.perimeters,
                dataclasses.replace(
                    current.perimeters[-1],
                    observation_time=growth_time,
                    area=(1500 if current.identifiers else 125) * units.acres,
                ),
            ),
        )
        for current in fires
    ]
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        growing,
        growth_time,
    )
    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        growth_time,
    )
    latest = {entry.name: entry for entry in snapshot.updates[-2:]}
    assert latest["Timber"].previous_mapped_area == peri_scribe.updates.Acreage(
        value=100,
    )
    assert latest["Timber Complex"].previous_mapped_area == peri_scribe.updates.Acreage(
        value=1234.5,
    )


def test_prepare_updates_enriches_a_local_namesake_without_taking_the_original_history(
    tmp_path: pathlib.Path,
) -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    renamed = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_renamed(
            tmp_path,
            now,
        )
    )
    namesake = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.distant_namesake(
            now,
        )
    )
    later = now + datetime.timedelta(minutes=3)
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [namesake, renamed],
        later,
    )
    enriched = dataclasses.replace(namesake, identifiers=frozenset({"2026-other"}))
    prepared = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            [enriched, renamed],
            later + datetime.timedelta(minutes=1),
        )
    )
    assert prepared.records == ()
    growth_time = later + datetime.timedelta(minutes=2)
    growing = dataclasses.replace(
        enriched,
        name="Timber Ridge",
        perimeters=(
            *enriched.perimeters,
            dataclasses.replace(
                enriched.perimeters[-1],
                observation_time=growth_time,
                area=125 * units.acres,
            ),
        ),
    )
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [growing, renamed],
        growth_time,
    )
    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        growth_time,
    )
    assert snapshot.updates[-1].name == "Timber Ridge"
    assert snapshot.updates[-1].previous_mapped_area == peri_scribe.updates.Acreage(
        value=100,
    )
    assert snapshot.updates[-1].log_identity == snapshot.updates[-2].log_identity
    assert snapshot.updates[-1].log_identity != snapshot.updates[0].log_identity


@pytest.mark.parametrize("empty_history", [False, True])
def test_prepare_updates_keeps_empty_name_only_history_stable(
    tmp_path: pathlib.Path,
    *,
    empty_history: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    unmapped = dataclasses.replace(
        fire,
        identifiers=frozenset(),
        perimeters=(
            ()
            if empty_history
            else (dataclasses.replace(fire.perimeters[-1], geometry=shapely.Polygon()),)
        ),
    )
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    first = tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [unmapped],
        now,
    )
    repeated = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            [unmapped],
            now + datetime.timedelta(minutes=1),
        )
    )
    assert first.records == ()
    assert repeated == first


@pytest.mark.parametrize("identified", [False, True])
@pytest.mark.parametrize("current_name", ["Timber", "timber"])
def test_prepare_updates_does_not_choose_between_matching_historical_names(
    tmp_path: pathlib.Path,
    current_name: str,
    *,
    identified: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    fire = dataclasses.replace(fire, name=current_name)
    current = fire if identified else dataclasses.replace(fire, identifiers=frozenset())
    signature = peri_scribe.fire_updates.perimeter_signature(fire.perimeters[-1])
    historical_keys = [json.dumps(["name", name]) for name in ("TIMBER", "Timber")]
    previous = peri_scribe.fire_updates.State(
        perimeters={key: frozenset({signature}) for key in historical_keys},
    )
    peri_scribe.publication.write_state(
        peri_scribe.fire_updates.state_path(tmp_path),
        previous,
    )
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)

    prepared = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            [current],
            now,
        )
    )

    assert len(prepared.records) == 1
    assert json.dumps(prepared.records[0]["log_identity"]) not in historical_keys
    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        now,
    )
    assert snapshot.updates[0].previous_mapped_area is None
    recased = dataclasses.replace(current, name="TIMBER")
    enriched = dataclasses.replace(recased, identifiers=fire.identifiers)
    for offset, replayed in enumerate((current, recased, enriched), start=1):
        repeated = (
            tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
                tmp_path,
                [replayed],
                now + datetime.timedelta(minutes=offset),
            )
        )
        assert repeated.records == ()


@pytest.mark.parametrize("with_growth", [False, True])
@pytest.mark.parametrize(
    ("original_name", "enriched_name"),
    [("TIMBER", "Timber"), ("  TIMBER-RIDGE / FIRE  ", "Timber Ridge Fire")],
)
def test_prepare_updates_preserves_history_when_first_identifier_changes_name_case(
    tmp_path: pathlib.Path,
    original_name: str,
    enriched_name: str,
    *,
    with_growth: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = dataclasses.replace(fire, name=original_name, identifiers=frozenset())
    fire = dataclasses.replace(fire, name=enriched_name)
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [original],
        now,
    )
    if with_growth:
        fire = dataclasses.replace(
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
    fires = tests.helpers.factories.peri_scribe.fire_updates_ownership.grouped_fires([
        original,
        fire,
    ])
    assert len(fires) == 1
    assert fires[0].name == enriched_name
    assert fires[0].identifiers == fire.identifiers
    later = now + datetime.timedelta(minutes=1)

    prepared = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            fires,
            later,
        )
    )

    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        later,
    )
    if with_growth:
        assert len(prepared.records) == 1
        assert [entry.mapped_area.value for entry in snapshot.updates] == [1234.5, 1500]
        update = snapshot.updates[-1]
        assert update.previous_mapped_area == peri_scribe.updates.Acreage(value=1234.5)
        change = update.mapped_area.quantity() - update.previous_mapped_area.quantity()
        assert change.m_as("acres") == pytest.approx(265.5)
    else:
        assert prepared.records == ()
        assert len(snapshot.updates) == 1
    repeated = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
            tmp_path,
            fires,
            later + datetime.timedelta(minutes=1),
        )
    )
    assert repeated.records == ()
