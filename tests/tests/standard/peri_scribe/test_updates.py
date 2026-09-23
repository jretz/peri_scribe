"""Publish a recent snapshot without losing the history needed for acreage changes."""

import compression.zstd
import datetime
import importlib.resources
import json
import os
import pathlib

import pydantic
import pytest
import time_machine

import peri_scribe.updates
import tests.helpers.doubles.errors
import tests.helpers.factories.peri_scribe.updates
from measurement_units import units


def test_read_entries_includes_archived_history_only_from_fire_update_logs(
    tmp_path: pathlib.Path,
) -> None:
    old = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    new = old.model_copy(
        update={
            "timestamp": datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
        },
    )
    logs = tmp_path / "logs"
    tests.helpers.factories.peri_scribe.updates.write_log(
        logs / "2026-08-fire-updates.jsonl.zst",
        [old],
    )
    tests.helpers.factories.peri_scribe.updates.write_log(
        logs / "2026-09-fire-updates.jsonl",
        [new],
    )
    with (logs / "2026-09-fire-updates.jsonl").open("a") as stream:
        stream.write("\n  \n")
    (logs / "2026-09.jsonl").write_text("diagnostic log")
    (logs / "2026-09-fire-updates.jsonl.backup").write_text("backup")

    assert peri_scribe.updates.read_entries(tmp_path) == (old, new)


def test_read_entries_handles_a_missing_log_directory(tmp_path: pathlib.Path) -> None:
    assert peri_scribe.updates.read_entries(tmp_path) == ()


def test_read_entries_skips_history_removed_during_the_lookup(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = tests.helpers.factories.peri_scribe.updates.entry(
        datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC),
        100 * units.acres,
    )
    current = previous.model_copy(
        update={"timestamp": datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)},
    )
    for filename, entry in [
        ("2026-08-fire-updates.jsonl.zst", previous),
        ("2026-09-fire-updates.jsonl", current),
    ]:
        tests.helpers.factories.peri_scribe.updates.write_log(
            tmp_path / "logs" / filename,
            [entry],
        )
    monkeypatch.setattr(
        compression.zstd,
        "open",
        tests.helpers.doubles.errors.raising_stub(FileNotFoundError("removed")),
    )

    assert peri_scribe.updates.read_entries(tmp_path) == (current,)


def test_snapshot_from_entries_compares_every_update_with_its_predecessor() -> None:
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now - offset,
            area * units.acres,
        )
        for offset, area in [
            (datetime.timedelta(days=10), 100),
            (datetime.timedelta(hours=3), 120),
            (datetime.timedelta(hours=2), 120),
            (datetime.timedelta(hours=1), 110),
            (datetime.timedelta(), 130),
        ]
    ]

    snapshot = peri_scribe.updates.snapshot_from_entries(reversed(entries), now)

    assert [update.mapped_area.value for update in snapshot.updates] == [120, 110, 130]
    assert [
        update.previous_mapped_area.value
        for update in snapshot.updates
        if update.previous_mapped_area is not None
    ] == [100, 120, 110]


@pytest.mark.parametrize(
    ("age", "included"),
    [
        (datetime.timedelta(microseconds=-1), False),
        (datetime.timedelta(), True),
        (datetime.timedelta(hours=48, microseconds=-1), True),
        (datetime.timedelta(hours=48), False),
        (datetime.timedelta(hours=49), False),
    ],
)
def test_snapshot_from_entries_uses_an_elapsed_48_hour_window(
    age: datetime.timedelta,
    *,
    included: bool,
) -> None:
    now = datetime.datetime.fromisoformat("2026-11-01T02:00:00-08:00")
    entry = tests.helpers.factories.peri_scribe.updates.entry(
        now.astimezone(datetime.UTC) - age,
        123 * units.acres,
    )

    snapshot = peri_scribe.updates.snapshot_from_entries([entry], now)

    assert bool(snapshot.updates) is included
    assert snapshot.generated_at == now


def test_snapshot_from_entries_keeps_distinct_fires_and_name_only_identities() -> None:
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    entries = [
        tests.helpers.factories.peri_scribe.updates.entry(
            now,
            123 * units.acres,
            identifier=identifier,
        )
        for identifier in ["first", "second", None]
    ]

    snapshot = peri_scribe.updates.snapshot_from_entries(entries, now)

    assert len(snapshot.updates) == len(entries)
    assert all(update.previous_mapped_area is None for update in snapshot.updates)


def test_snapshot_from_entries_keeps_distinct_local_namesake_histories() -> None:
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    entries = []
    for age, acreage, identity in [
        (3, 100, ("name", "Timber")),
        (2, 50, ("local", "new-timber")),
        (1, 75, ("local", "new-timber")),
    ]:
        entry = tests.helpers.factories.peri_scribe.updates.entry(
            now - datetime.timedelta(hours=age),
            acreage * units.acres,
            identifier=None,
        )
        entries.append(
            peri_scribe.updates.LogEntry.model_validate({
                **entry.model_dump(),
                "log_identity": identity,
            }),
        )

    snapshot = peri_scribe.updates.snapshot_from_entries(entries, now)

    assert len(snapshot.updates) == len(entries)
    assert [
        update.previous_mapped_area.value
        if update.previous_mapped_area is not None
        else None
        for update in snapshot.updates
    ] == [None, None, 50]


def test_snapshot_from_entries_omits_an_initial_zero_acreage() -> None:
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    entry = tests.helpers.factories.peri_scribe.updates.entry(now, 0 * units.acres)

    assert peri_scribe.updates.snapshot_from_entries([entry], now).updates == ()


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_acreage_rejects_invalid_measurements(value: float) -> None:
    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.Acreage(value=value)


def test_log_entry_requires_an_aware_timestamp() -> None:
    with pytest.raises(pydantic.ValidationError):
        tests.helpers.factories.peri_scribe.updates.entry(
            datetime.datetime(2026, 9, 22),
            123 * units.acres,
        )


def test_write_html_leaves_an_identical_viewer_untouched(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "maps" / "updates.html"
    peri_scribe.updates.write_html(path)
    os.utime(path, ns=(1, 1))

    peri_scribe.updates.write_html(path)

    assert path.stat().st_mtime_ns == 1


def test_write_html_replaces_an_outdated_viewer(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "updates.html"
    path.write_text("outdated")

    peri_scribe.updates.write_html(path)

    resource = importlib.resources.files("peri_scribe").joinpath("updates.html")
    assert path.read_bytes() == resource.read_bytes()


def test_write_html_preserves_the_previous_viewer_on_write_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "updates.html"
    path.write_text("previous viewer")
    monkeypatch.setattr(
        pathlib.Path,
        "write_bytes",
        tests.helpers.doubles.errors.raising_stub(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        peri_scribe.updates.write_html(path)

    assert path.read_text() == "previous viewer"


@pytest.mark.parametrize("missing_history", [False, True])
def test_write_updates_page_uses_available_history_across_month_boundaries(
    tmp_path: pathlib.Path,
    *,
    missing_history: bool,
) -> None:
    now = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    previous = tests.helpers.factories.peri_scribe.updates.entry(
        now - datetime.timedelta(days=10),
        100 * units.acres,
    )
    current = tests.helpers.factories.peri_scribe.updates.entry(now, 123 * units.acres)
    if not missing_history:
        tests.helpers.factories.peri_scribe.updates.write_log(
            tmp_path / "logs" / "2026-08-fire-updates.jsonl.zst",
            [previous],
        )
    tests.helpers.factories.peri_scribe.updates.write_log(
        tmp_path / "logs" / "2026-09-fire-updates.jsonl",
        [current],
    )

    with time_machine.travel(now, tick=False):
        peri_scribe.updates.write_updates_page(tmp_path)

    result = json.loads((tmp_path / "maps" / "updates.json").read_text())
    assert result == {
        "version": 1,
        "generated_at": "2026-09-01T00:00:00Z",
        "updates": [
            {
                **current.model_dump(mode="json"),
                "previous_mapped_area": (
                    None if missing_history else {"value": 100, "units": "acre"}
                ),
            },
        ],
    }
    assert (tmp_path / "maps" / "updates.html").exists()


def test_write_updates_page_expires_data_even_without_new_log_entries(
    tmp_path: pathlib.Path,
) -> None:
    now = datetime.datetime(2026, 9, 22, tzinfo=datetime.UTC)
    tests.helpers.factories.peri_scribe.updates.write_log(
        tmp_path / "logs" / "2026-09-fire-updates.jsonl",
        [tests.helpers.factories.peri_scribe.updates.entry(now, 123 * units.acres)],
    )
    with time_machine.travel(now, tick=False):
        peri_scribe.updates.write_updates_page(tmp_path)
    with time_machine.travel(now + datetime.timedelta(hours=48), tick=False):
        peri_scribe.updates.write_updates_page(tmp_path)

    result = json.loads((tmp_path / "maps" / "updates.json").read_text())
    assert result["updates"] == []


def test_write_updates_page_preserves_outputs_when_a_log_is_corrupt(
    tmp_path: pathlib.Path,
) -> None:
    peri_scribe.updates.write_updates_page(tmp_path)
    path = tmp_path / "maps" / "updates.json"
    original = path.read_bytes()
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-09-fire-updates.jsonl").write_text("incomplete record")

    with pytest.raises(pydantic.ValidationError):
        peri_scribe.updates.write_updates_page(tmp_path)

    assert path.read_bytes() == original
