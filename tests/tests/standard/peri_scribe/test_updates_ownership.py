"""Reproject current history ownership without modifying immutable logged evidence."""

import datetime
import json
import pathlib

import pydantic
import pytest
import time_machine

import peri_scribe.fire_updates
import peri_scribe.publication
import peri_scribe.updates
import tests.helpers.factories.peri_scribe.updates
from measurement_units import units


def test_snapshot_from_entries_combines_projected_predecessors_before_window() -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=age),
            area * units.acres,
            log_identity=("local", bucket),
        )
        for bucket, age, area in [
            ("first", 72, 100),
            ("second", 3, 200),
            ("first", 2, 200),
            ("second", 1, 150),
            ("first", -1, 500),
        ]
    ]
    before = tuple(entry.model_dump_json() for entry in entries)
    owners = {
        json.dumps(["local", bucket]): json.dumps(["id", "current"])
        for bucket in ("first", "second")
    }

    snapshot = peri_scribe.updates.snapshot_from_entries(
        reversed(entries),
        now,
        owners=owners,
    )

    assert [update.mapped_area.value for update in snapshot.updates] == [200, 150]
    assert [
        update.previous_mapped_area.value
        for update in snapshot.updates
        if update.previous_mapped_area is not None
    ] == [100, 200]
    assert all(
        update.history_identity == ("id", "current") for update in snapshot.updates
    )
    assert all(
        update.log_identity == ("local", "second") for update in snapshot.updates
    )
    assert tuple(entry.model_dump_json() for entry in entries) == before


@pytest.mark.parametrize(
    ("owners", "groups", "previous"),
    [
        ({"a": "b", "b": "c"}, ["b", "c", "b"], [None, None, 100]),
        ({"a": "b", "b": "a"}, ["b", "a", "b"], [None, None, 100]),
        ({"a": "b", "b": "b"}, ["b", "b", "b"], [None, 100, 200]),
    ],
)
def test_snapshot_from_entries_projects_ownership_exactly_once(
    owners: dict[str, str],
    groups: list[str],
    previous: list[int | None],
) -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=age),
            area * units.acres,
            log_identity=("local", bucket),
        )
        for bucket, age, area in [("a", 3, 100), ("b", 2, 200), ("a", 1, 300)]
    ]

    snapshot = peri_scribe.updates.snapshot_from_entries(
        entries,
        now,
        owners={
            json.dumps(["local", key]): json.dumps(["local", value])
            for key, value in owners.items()
        },
    )

    assert [update.history_identity for update in snapshot.updates] == [
        ("local", group) for group in groups
    ]
    assert [update.identity() for update in snapshot.updates] == [
        entry.identity() for entry in entries
    ]
    assert [
        update.previous_mapped_area.value if update.previous_mapped_area else None
        for update in snapshot.updates
    ] == previous


def test_snapshot_from_entries_reverses_corrections_without_merging_namesakes() -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=age),
            area * units.acres,
            identifier=None,
            log_identity=("local", bucket),
        )
        for bucket, age, area in [("a", 3, 100), ("b", 2, 200), ("a", 1, 300)]
    ]
    independent = {
        json.dumps(["local", bucket]): json.dumps(["local", bucket])
        for bucket in ("a", "b")
    }
    joined = dict.fromkeys(independent, json.dumps(["local", "b"]))
    original = peri_scribe.updates.snapshot_from_entries(
        entries,
        now,
        owners=independent,
    )
    merged = peri_scribe.updates.snapshot_from_entries(entries, now, owners=joined)
    corrected = peri_scribe.updates.snapshot_from_entries(
        entries,
        now,
        owners=independent,
    )

    assert corrected == original
    assert {update.history_identity for update in original.updates} == {
        ("local", "a"),
        ("local", "b"),
    }
    assert {update.history_identity for update in merged.updates} == {("local", "b")}
    assert original.updates[-1].previous_mapped_area == peri_scribe.updates.Acreage(
        value=100,
    )
    assert merged.updates[-1].previous_mapped_area == peri_scribe.updates.Acreage(
        value=200,
    )


@pytest.mark.parametrize("owner", ['["invalid", "a"]', '["local", 1]', '"owner"', "[]"])
def test_snapshot_from_entries_rejects_malformed_owner_identity(owner: str) -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.snapshot_from_entries(
            [],
            now,
            owners={'["local", "a"]': owner},
        )


def test_snapshot_accepts_legacy_update_without_current_owner() -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    entry = tests.helpers.factories.peri_scribe.updates.entry(now, 100 * units.acres)
    legacy = {**entry.model_dump(), "previous_mapped_area": None}

    snapshot = peri_scribe.updates.Snapshot.model_validate(
        {"generated_at": now, "updates": [legacy]},
    )

    assert snapshot.updates[0].history_identity is None
    assert snapshot.updates[0].identity() == entry.identity()


def test_write_updates_page_applies_and_reverses_saved_owners_without_log_edits(
    tmp_path: pathlib.Path,
) -> None:
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=age),
            area * units.acres,
            log_identity=("local", bucket),
        )
        for bucket, age, area in [("a", 3, 100), ("b", 2, 200), ("a", 1, 300)]
    ]
    log = tmp_path / "logs" / "2026-09-fire-updates.jsonl"
    tests.helpers.factories.peri_scribe.updates.write_log(log, entries)
    original = log.read_bytes()
    first = json.dumps(["local", "a"])
    second = json.dumps(["local", "b"])
    snapshots = []
    for owners in (
        {first: first, second: second},
        {first: second, second: second},
        {first: first, second: second},
    ):
        peri_scribe.publication.write_state(
            peri_scribe.fire_updates.state_path(tmp_path),
            peri_scribe.fire_updates.State(owners=owners),
        )
        with time_machine.travel(now, tick=False):
            peri_scribe.updates.write_updates_page(tmp_path)
        snapshots.append(
            peri_scribe.updates.Snapshot.model_validate_json(
                (tmp_path / "maps" / "updates.json").read_text(),
            ),
        )
        assert log.read_bytes() == original
        assert [update.log_identity for update in snapshots[-1].updates] == [
            entry.log_identity for entry in entries
        ]
    assert snapshots[0] == snapshots[2]
    assert snapshots[0] != snapshots[1]
