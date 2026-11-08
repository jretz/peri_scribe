"""Decorate visible updates without changing immutable logged occurrences."""

import dataclasses
import datetime
import pathlib

import geopandas
import pydantic
import pytest
import shapely
import time_machine

import peri_scribe.presentation.fire_data
import peri_scribe.previews
import peri_scribe.report.gathering
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.fire_updates_ownership
import tests.helpers.factories.peri_scribe.fire_updates_transfer
import tests.helpers.factories.peri_scribe.previews
import tests.helpers.factories.peri_scribe.report.locations
import tests.helpers.factories.peri_scribe.updates
from measurement_units import units


@pytest.mark.parametrize("reverse_order", [False, True])
def test_write_updates_page_uses_current_bucket_owner_after_a_split(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reverse_order: bool,
) -> None:
    previews = {
        "Timber": "data:image/webp;base64,dGltYmVy",
        "Latest": "data:image/webp;base64,bGF0ZXN0",
        "Older": "data:image/webp;base64,b2xkZXI=",
    }
    monkeypatch.setattr(
        peri_scribe.previews,
        "fire_preview",
        lambda fire: previews[fire.name],
    )
    now = tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH
    original = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a", "b"}),
        1,
    )
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        [original],
        now,
    )
    latest = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"b"}),
        3,
        name="Latest",
    )
    older = tests.helpers.factories.peri_scribe.fire_updates_transfer.fire(
        frozenset({"a"}),
        2,
        name="Older",
    )
    fires = [older, latest] if reverse_order else [latest, older]
    now += datetime.timedelta(minutes=1)
    tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_updates(
        tmp_path,
        fires,
        now,
    )
    monkeypatch.setattr(
        peri_scribe.report.gathering,
        "fire_location",
        lambda fire, _cities: f"Near {fire.name}",
    )
    with time_machine.travel(now, tick=False):
        peri_scribe.updates.write_updates_page(tmp_path, fires=fires)
    snapshot = peri_scribe.updates.Snapshot.model_validate_json(
        (tmp_path / "maps" / "updates.json").read_bytes(),
    )
    assert {update.name: update.preview for update in snapshot.updates} == previews
    assert {update.name: update.location for update in snapshot.updates} == {
        "Timber": "Near Latest",
        "Latest": "Near Latest",
        "Older": "Near Older",
    }


def test_write_updates_page_keeps_preview_when_name_history_gains_an_identifier(
    tmp_path: pathlib.Path,
) -> None:
    now = tests.helpers.factories.peri_scribe.fire_updates_transfer.EPOCH
    renamed = (
        tests.helpers.factories.peri_scribe.fire_updates_ownership.publish_renamed(
            tmp_path,
            now,
        )
    )
    with time_machine.travel(now + datetime.timedelta(minutes=3), tick=False):
        peri_scribe.updates.write_updates_page(tmp_path, fires=[renamed])
    snapshot = peri_scribe.updates.Snapshot.model_validate_json(
        (tmp_path / "maps" / "updates.json").read_bytes(),
    )
    assert snapshot.updates
    assert all(update.preview is not None for update in snapshot.updates)


def test_with_previews_omits_legacy_rows_without_matching_acreage() -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=index),
            (100 + index) * units.acres,
            identifier="alias",
            name="Old name",
        )
        for index in (2, 1)
    ]
    unmatched = tests.helpers.factories.peri_scribe.updates.entry(
        now,
        20 * units.acres,
        identifier="other",
    )
    snapshot = peri_scribe.updates.snapshot_from_entries([*entries, unmatched], now)
    projected = snapshot.updates[0].model_copy(
        update={"history_identity": ("component", "timber-component")},
    )
    snapshot = snapshot.model_copy(
        update={"updates": (projected, *snapshot.updates[1:])},
    )
    result = peri_scribe.updates.with_previews(
        snapshot,
        [fire],
        geopandas.GeoDataFrame(),
    )
    assert result == snapshot


def test_with_previews_omits_missing_geometry_without_conflating_namesakes() -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    fire = dataclasses.replace(
        tests.helpers.factories.peri_scribe.previews.fire(),
        perimeters=(),
    )
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now,
            100 * units.acres,
            identifier=identifier,
        )
        for identifier in ("alias", None)
    ]
    result = peri_scribe.updates.with_previews(
        peri_scribe.updates.snapshot_from_entries(entries, now),
        [fire],
        geopandas.GeoDataFrame(),
    )
    assert all(update.preview is None for update in result.updates)
    assert all("preview" not in update.model_dump() for update in result.updates)


def test_write_updates_page_reconstructs_legacy_previews_from_each_mapping(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.datetime(2026, 9, 22, 12, tzinfo=datetime.UTC)
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    correction = dataclasses.replace(
        fire.perimeters[-1],
        geometry=shapely.box(-121.008, 35.996, -120.992, 36.010),
    )
    fire = dataclasses.replace(
        fire,
        perimeters=(*fire.perimeters[:2], correction),
        progression_rings=(),
    )
    rendered = []
    render = peri_scribe.previews.fire_preview

    def capture(mapping: peri_scribe.presentation.fire_data.FireSummary) -> str | None:
        """Observe the dated mapping supplied to the real renderer.

        Args:
            mapping: The perimeter and ring history selected for a row.

        Returns:
            The actual encoded preview for that mapping.
        """
        rendered.append(mapping)
        return render(mapping)

    monkeypatch.setattr(peri_scribe.previews, "fire_preview", capture)
    entries = (
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(days=1),
            2 * units.acres,
            identifier="alias",
        ),
        tests.helpers.factories.peri_scribe.updates.entry(
            now,
            3 * units.acres,
            identifier="alias",
        ),
    )
    tests.helpers.factories.peri_scribe.updates.write_log(
        tmp_path / "logs" / "2026-09-fire-updates.jsonl",
        entries,
    )
    with time_machine.travel(now, tick=False):
        peri_scribe.updates.write_updates_page(tmp_path, fires=[fire])
    snapshot = peri_scribe.updates.Snapshot.model_validate_json(
        (tmp_path / "maps" / "updates.json").read_bytes(),
    )
    earlier, later = rendered
    assert earlier.perimeters == fire.perimeters[:2]
    assert later.perimeters == fire.perimeters
    retracted = shapely.Point(-121.009, 36.003)
    assert earlier.progression_rings[0].geometry.covers(retracted)
    assert not any(ring.geometry.covers(retracted) for ring in later.progression_rings)
    assert all(update.preview is not None for update in snapshot.updates)
    assert snapshot.updates[0].preview != snapshot.updates[1].preview
    assert peri_scribe.updates.read_entries(tmp_path) == entries


def test_with_previews_omits_legacy_preview_when_latest_observation_is_tied() -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    tied = dataclasses.replace(
        fire.perimeters[0],
        observation_time=fire.perimeters[-1].observation_time,
    )
    fire = dataclasses.replace(
        fire,
        perimeters=(*fire.perimeters[:-1], tied, fire.perimeters[-1]),
    )
    entry = tests.helpers.factories.peri_scribe.updates.entry(
        now,
        3 * units.acres,
        identifier="alias",
    )
    snapshot = peri_scribe.updates.snapshot_from_entries([entry], now)
    result = peri_scribe.updates.with_previews(
        snapshot,
        [fire],
        geopandas.GeoDataFrame(),
    )

    assert result.updates[0].preview is None


def test_with_previews_keeps_recorded_absence_when_geometry_is_available() -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    entry = tests.helpers.factories.peri_scribe.updates.entry(
        now,
        3 * units.acres,
        identifier="alias",
    ).model_copy(update={"preview": None})
    snapshot = peri_scribe.updates.snapshot_from_entries([entry], now)
    result = peri_scribe.updates.with_previews(
        snapshot,
        [fire],
        geopandas.GeoDataFrame(),
    )

    assert "preview" not in result.updates[0].model_dump()


def test_write_updates_page_refreshes_locations_without_rewriting_history(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    entries = tuple(
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=index),
            (100 + index) * units.acres,
            identifier="alias",
            location=f"Recorded location {index}",
        )
        for index in (2, 1)
    )
    unmatched = tests.helpers.factories.peri_scribe.updates.entry(
        now,
        20 * units.acres,
        identifier="other",
    )
    entries = (*entries, unmatched)
    path = tmp_path / "logs" / "2026-09-fire-updates.jsonl"
    tests.helpers.factories.peri_scribe.updates.write_log(path, entries)
    before = path.read_bytes()
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        ("Current city", "CA", (-121.005, 36.003)),
    ])
    monkeypatch.setattr(
        peri_scribe.report.gathering,
        "read_cities_layer",
        lambda _year: cities,
    )
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    with time_machine.travel(now, tick=False):
        peri_scribe.updates.write_updates_page(tmp_path, fires=[fire])
    result = peri_scribe.updates.Snapshot.model_validate_json(
        (tmp_path / "maps" / "updates.json").read_bytes(),
    )
    original = peri_scribe.updates.snapshot_from_entries(entries, now)
    assert result.updates[0].location == "0 mi from Current city, CA"
    assert result.updates[1].location == "0 mi from Current city, CA"
    assert result.updates[2] == original.updates[2]
    for recorded, decorated in zip(original.updates, result.updates, strict=True):
        assert decorated.model_dump(exclude={"preview", "location"}) == (
            recorded.model_dump(exclude={"preview", "location"})
        )
    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", ["cities", "geometry"])
def test_with_previews_preserves_location_when_current_location_is_unavailable(
    missing: str,
) -> None:
    now = datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)
    fire = tests.helpers.factories.peri_scribe.previews.fire()
    cities = tests.helpers.factories.peri_scribe.report.locations.city_frame([
        ("Current city", "CA", (-121.005, 36.003)),
    ])
    if missing == "cities":
        cities = geopandas.GeoDataFrame()
    else:
        fire = dataclasses.replace(fire, perimeters=())
    entry = tests.helpers.factories.peri_scribe.updates.entry(
        now,
        100 * units.acres,
        identifier="alias",
        location="Recorded location",
    )
    snapshot = peri_scribe.updates.snapshot_from_entries([entry], now)
    result = peri_scribe.updates.with_previews(snapshot, [fire], cities)
    assert result.updates[0].location == "Recorded location"


@pytest.mark.parametrize(
    "preview",
    [
        "https://example.com/image.webp",
        "data:image/png;base64,AAAA",
        "data:image/webp;base64,",
        "data:image/webp;base64,a-b_",
    ],
)
def test_update_rejects_non_webp_or_non_base64_preview(preview: str) -> None:
    entry = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.Update(
            **entry.model_dump(exclude_unset=True),
            previous_mapped_area=None,
            preview=preview,
        )
