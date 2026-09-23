"""Only new mapped observations from completed KMZs produce fire updates."""

import dataclasses
import datetime
import json
import pathlib
import zoneinfo

import pytest
import shapely
import time_machine

import peri_scribe.fire_updates
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.report.gathering
import peri_scribe.updates
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.fire_updates
import tests.helpers.factories.peri_scribe.report.locations
from measurement_units import units


@pytest.mark.parametrize("legacy_state", [False, True])
def test_prepare_updates_keeps_identity_when_a_preferred_identifier_arrives(
    tmp_path: pathlib.Path,
    *,
    legacy_state: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    identifier = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    original = dataclasses.replace(fire, identifiers=frozenset({identifier}))
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores)
    peri_scribe.fire_updates.write_updates(tmp_path, prepared)
    if legacy_state:
        path = peri_scribe.fire_updates.state_path(tmp_path)
        state = json.loads(path.read_text())
        state.pop("aliases", None)
        path.write_text(json.dumps(state))
    enriched = dataclasses.replace(fire, identifiers=fire.identifiers | {identifier})

    repeated = peri_scribe.fire_updates.prepare_updates(tmp_path, [enriched], scores)

    assert repeated.records == ()


def test_write_updates_preserves_acreage_history_after_identifier_enrichment(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    identifier = "286b7f1d-8945-4a5d-9d81-5235c18af1fe"
    original = dataclasses.replace(fire, identifiers=frozenset({identifier}))
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    with time_machine.travel(now, tick=False):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, [original], scores),
        )
    enriched = dataclasses.replace(fire, identifiers=fire.identifiers | {identifier})
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [enriched], scores),
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

    snapshot = peri_scribe.updates.snapshot_from_entries(
        peri_scribe.updates.read_entries(tmp_path),
        later,
    )

    assert [entry.mapped_area.value for entry in snapshot.updates] == [1234.5, 1500]
    assert {entry.identifier for entry in snapshot.updates} == {identifier}
    assert snapshot.updates[-1].previous_mapped_area == peri_scribe.updates.Acreage(
        value=1234.5,
    )


def test_prepare_updates_shares_report_locations_and_uses_mapped_acres(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        ("Soledad", "CA", (-121.326, 36.4247)),
    ])
    monkeypatch.setattr(
        peri_scribe.report.gathering,
        "read_cities_layer",
        lambda _directory: cities,
    )
    scores = peri_scribe.models.FireScores(
        version="test",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name=fire.name,
                identifier="2026-calpf-002271",
                score=100,
                explanation="Interesting",
            ),
        ],
    )
    report = peri_scribe.report.gathering.report_from_fires([fire], scores, tmp_path)
    updates = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)

    assert len(report.type_one_fires) == len(report.top_fires) == 1
    assert report.fire_details[0].location is not None
    assert updates.records == (
        {
            "log_identity": ["id", "2026-calpf-002271"],
            "identifier": "2026-calpf-002271",
            "name": "Timber",
            "location": report.fire_details[0].location,
            "mapped_area": {"value": 1234.5, "units": "acre"},
        },
    )
    assert not peri_scribe.fire_updates.state_path(tmp_path).exists()
    assert not (tmp_path / "logs").exists()


def test_write_updates_does_not_repeat_unchanged_perimeters(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    when = datetime.datetime(
        2026,
        9,
        22,
        10,
        tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles"),
    )
    with time_machine.travel(when, tick=False):
        updates = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        peri_scribe.fire_updates.write_updates(tmp_path, updates)
        repeated = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        peri_scribe.fire_updates.write_updates(tmp_path, repeated)
    assert repeated.records == ()
    path = tmp_path / "logs" / "2026-09-fire-updates.jsonl"
    record = json.loads(path.read_text())
    assert record.pop("batch_id")
    assert record == {
        **updates.records[0],
        "timestamp": "2026-09-22T10:00:00-0700",
    }


@pytest.mark.parametrize("changed_shape", [False, True])
def test_prepare_updates_retains_changes_until_successful_completion(
    tmp_path: pathlib.Path,
    *,
    changed_shape: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    peri_scribe.fire_updates.write_updates(
        tmp_path,
        peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores),
    )
    previous = fire.perimeters[-1]
    perimeter = dataclasses.replace(
        previous,
        geometry=(
            shapely.box(-121.6, 36.2, -121.5, 36.3)
            if changed_shape
            else previous.geometry
        ),
        observation_time=(
            previous.observation_time
            if changed_shape
            else datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
        ),
    )
    changed = dataclasses.replace(fire, perimeters=(*fire.perimeters, perimeter))
    first_attempt = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [changed],
        scores,
    )
    retry = peri_scribe.fire_updates.prepare_updates(tmp_path, [changed], scores)
    assert first_attempt == retry
    assert len(retry.records) == 1
    peri_scribe.fire_updates.write_updates(tmp_path, retry)
    assert not peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [changed],
        scores,
    ).records


def test_prepare_updates_tracks_uninteresting_fires_without_logging_them(
    tmp_path: pathlib.Path,
) -> None:
    interesting = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    ordinary = dataclasses.replace(interesting, type_one=False)
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    baseline = peri_scribe.fire_updates.prepare_updates(tmp_path, [ordinary], scores)
    assert baseline.records == ()
    peri_scribe.fire_updates.write_updates(tmp_path, baseline)
    assert not peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [interesting],
        scores,
    ).records


@pytest.mark.parametrize("empty_geometry", [False, True])
def test_prepare_updates_omits_fires_without_mapped_perimeters(
    tmp_path: pathlib.Path,
    *,
    empty_geometry: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    fire = dataclasses.replace(
        fire,
        perimeters=(
            (dataclasses.replace(fire.perimeters[-1], geometry=shapely.Polygon()),)
            if empty_geometry
            else ()
        ),
    )
    updates = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [fire],
        peri_scribe.models.FireScores(version="test", fires=[]),
    )
    assert updates.records == ()


def test_prepare_updates_distinguishes_same_named_fires(tmp_path: pathlib.Path) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    other = dataclasses.replace(fire, identifiers=frozenset({"2026-other"}))
    updates = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [fire, other],
        peri_scribe.models.FireScores(version="test", fires=[]),
    )
    assert {entry["identifier"] for entry in updates.records} == {
        "2026-calpf-002271",
        "2026-other",
    }


def test_prepare_updates_supports_name_only_fires(tmp_path: pathlib.Path) -> None:
    fire = dataclasses.replace(
        tests.helpers.factories.peri_scribe.fire_updates.mapped_fire(),
        identifiers=frozenset(),
    )
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    updates = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
    peri_scribe.fire_updates.write_updates(tmp_path, updates)

    assert updates.records[0]["identifier"] is None
    assert not peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [fire],
        scores,
    ).records


def test_prepare_updates_remembers_fires_missing_from_an_intermediate_build(
    tmp_path: pathlib.Path,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    for fires in ([fire], []):
        peri_scribe.fire_updates.write_updates(
            tmp_path,
            peri_scribe.fire_updates.prepare_updates(tmp_path, fires, scores),
        )

    assert not peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [fire],
        scores,
    ).records


def test_prepare_updates_converts_stored_area_to_acres(tmp_path: pathlib.Path) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    area = 50000.0 * units.Unit("meters ** 2")
    fire = dataclasses.replace(
        fire,
        perimeters=(dataclasses.replace(fire.perimeters[-1], area=area),),
    )
    updates = peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [fire],
        peri_scribe.models.FireScores(version="test", fires=[]),
    )
    assert updates.records[0]["mapped_area"] == {
        "value": pytest.approx(area.m_as("acres")),
        "units": "acre",
    }


def test_write_updates_keeps_baseline_when_append_fails(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    baseline = peri_scribe.fire_updates.prepare_updates(tmp_path, [], scores)
    peri_scribe.fire_updates.write_updates(tmp_path, baseline)
    saved = peri_scribe.fire_updates.state_path(tmp_path).read_bytes()
    updates = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
    monkeypatch.setattr(
        peri_scribe.logging,
        "append_monthly_records",
        tests.helpers.doubles.errors.raising_stub(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        peri_scribe.fire_updates.write_updates(tmp_path, updates)
    assert peri_scribe.fire_updates.state_path(tmp_path).read_bytes() == saved


def test_perimeter_signature_ignores_ring_orientation_and_timezone() -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = fire.perimeters[0]
    equivalent = dataclasses.replace(
        original,
        geometry=shapely.reverse(original.geometry),
        observation_time=datetime.datetime.fromisoformat("2025-12-31T16:00:00-08:00"),
    )
    assert peri_scribe.fire_updates.perimeter_signature(original) == (
        peri_scribe.fire_updates.perimeter_signature(equivalent)
    )


def test_perimeter_signature_supports_undated_mapping() -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    original = fire.perimeters[0]
    undated = dataclasses.replace(original, observation_time=None)
    assert peri_scribe.fire_updates.perimeter_signature(original) != (
        peri_scribe.fire_updates.perimeter_signature(undated)
    )
