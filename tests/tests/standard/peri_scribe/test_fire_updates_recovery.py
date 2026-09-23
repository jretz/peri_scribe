"""Publication retries preserve the original event without duplicating mapping."""

import dataclasses
import datetime
import pathlib

import pytest
import time_machine

import peri_scribe.fire_updates
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.publication
import peri_scribe.updates
import tests.helpers.doubles.errors
import tests.helpers.doubles.peri_scribe.fire_updates
import tests.helpers.factories.peri_scribe.fire_updates
from measurement_units import units


@pytest.mark.parametrize("prepare_again", [False, True])
@pytest.mark.parametrize(
    "retry_delay",
    [datetime.timedelta(minutes=5), datetime.timedelta(days=10)],
)
def test_write_updates_recovers_checkpoint_failure_without_repeating_original_event(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    retry_delay: datetime.timedelta,
    *,
    prepare_again: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    original_time = datetime.datetime(2026, 9, 30, 20, tzinfo=datetime.UTC)
    with time_machine.travel(original_time, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        with monkeypatch.context() as interrupted:
            interrupted.setattr(
                peri_scribe.publication,
                "write_state",
                tests.helpers.doubles.peri_scribe.fire_updates.failing_state_writer(
                    peri_scribe.fire_updates.state_path(tmp_path),
                ),
            )
            with pytest.raises(OSError, match="Interrupted state write"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    with time_machine.travel(original_time + retry_delay, tick=False):
        retry = (
            peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
            if prepare_again
            else prepared
        )
        peri_scribe.fire_updates.write_updates(tmp_path, retry)

    entries = peri_scribe.updates.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].timestamp == original_time
    assert entries[0].mapped_area.value == pytest.approx(1234.5)
    assert (
        peri_scribe.publication.read_state(
            peri_scribe.fire_updates.state_path(tmp_path),
            peri_scribe.fire_updates.State,
        )
        == prepared.state
    )


def test_prepare_updates_recovers_old_publication_before_comparing_new_mapping(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    original_time = datetime.datetime(2026, 9, 22, 18, tzinfo=datetime.UTC)
    next_time = original_time + datetime.timedelta(minutes=5)
    with time_machine.travel(original_time, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        with monkeypatch.context() as interrupted:
            interrupted.setattr(
                peri_scribe.publication,
                "write_state",
                tests.helpers.doubles.peri_scribe.fire_updates.failing_state_writer(
                    peri_scribe.fire_updates.state_path(tmp_path),
                ),
            )
            with pytest.raises(OSError, match="Interrupted state write"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    new_perimeter = dataclasses.replace(
        fire.perimeters[-1],
        observation_time=next_time,
        area=1350.0 * units.acres,
    )
    changed = dataclasses.replace(fire, perimeters=(*fire.perimeters, new_perimeter))
    with time_machine.travel(next_time, tick=False):
        newer = peri_scribe.fire_updates.prepare_updates(tmp_path, [changed], scores)
        assert (
            peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(tmp_path),
                peri_scribe.fire_updates.State,
            )
            == prepared.state
        )
        peri_scribe.fire_updates.write_updates(tmp_path, newer)

    entries = peri_scribe.updates.read_entries(tmp_path)
    assert [(entry.timestamp, entry.mapped_area.value) for entry in entries] == [
        (original_time, 1234.5),
        (next_time, 1350.0),
    ]
    assert not peri_scribe.fire_updates.prepare_updates(
        tmp_path,
        [changed],
        scores,
    ).records


def test_write_updates_recovers_failure_to_remove_completed_journal(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    original_time = datetime.datetime(2026, 9, 22, 18, tzinfo=datetime.UTC)
    journal = tmp_path / "derived" / "fire_updates_pending.json"
    with time_machine.travel(original_time, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        with monkeypatch.context() as interrupted:
            interrupted.setattr(
                pathlib.Path,
                "unlink",
                tests.helpers.doubles.peri_scribe.fire_updates.failing_unlink(journal),
            )
            with pytest.raises(OSError, match="Interrupted file removal"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)
        assert journal.exists()
        assert (
            peri_scribe.publication.read_state(
                peri_scribe.fire_updates.state_path(tmp_path),
                peri_scribe.fire_updates.State,
            )
            == prepared.state
        )

    with time_machine.travel(original_time + datetime.timedelta(minutes=5), tick=False):
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    entries = peri_scribe.updates.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].timestamp == original_time
    assert not journal.exists()


@pytest.mark.parametrize("fail_journal", [False, True])
def test_write_updates_retains_unwritten_mapping_after_early_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_journal: bool,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    original_time = datetime.datetime(2026, 9, 22, 18, tzinfo=datetime.UTC)
    retry_time = original_time + datetime.timedelta(minutes=5)
    with time_machine.travel(original_time, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        with monkeypatch.context() as interrupted:
            if fail_journal:
                interrupted.setattr(
                    peri_scribe.publication,
                    "write_state",
                    tests.helpers.doubles.peri_scribe.fire_updates.failing_state_writer(
                        tmp_path / "derived" / "fire_updates_pending.json",
                    ),
                )
            else:
                interrupted.setattr(
                    peri_scribe.logging,
                    "append_monthly_records",
                    tests.helpers.doubles.errors.raising_stub(OSError("Append failed")),
                )
            with pytest.raises(OSError, match=r"Interrupted state write|Append failed"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)
        assert not peri_scribe.fire_updates.state_path(tmp_path).exists()

    with time_machine.travel(retry_time, tick=False):
        retry = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        peri_scribe.fire_updates.write_updates(tmp_path, retry)

    entries = peri_scribe.updates.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].mapped_area.value == pytest.approx(1234.5)
    assert entries[0].timestamp == (retry_time if fail_journal else original_time)


def test_write_updates_recovers_failed_compression_without_duplicating_batch(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fire = tests.helpers.factories.peri_scribe.fire_updates.mapped_fire()
    scores = peri_scribe.models.FireScores(version="test", fires=[])
    original_time = datetime.datetime(2026, 9, 30, 20, tzinfo=datetime.UTC)
    with time_machine.travel(original_time, tick=False):
        prepared = peri_scribe.fire_updates.prepare_updates(tmp_path, [fire], scores)
        with monkeypatch.context() as interrupted:
            interrupted.setattr(
                peri_scribe.publication,
                "write_state",
                tests.helpers.doubles.peri_scribe.fire_updates.failing_state_writer(
                    peri_scribe.fire_updates.state_path(tmp_path),
                ),
            )
            with pytest.raises(OSError, match="Interrupted state write"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    with time_machine.travel(original_time + datetime.timedelta(days=10), tick=False):
        with monkeypatch.context() as interrupted:
            interrupted.setattr(
                pathlib.Path,
                "unlink",
                tests.helpers.doubles.peri_scribe.fire_updates.failing_unlink(
                    tmp_path / "logs" / "2026-09-fire-updates.jsonl",
                ),
            )
            with pytest.raises(OSError, match="Interrupted file removal"):
                peri_scribe.fire_updates.write_updates(tmp_path, prepared)
        peri_scribe.fire_updates.write_updates(tmp_path, prepared)

    entries = peri_scribe.updates.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0].timestamp == original_time
    assert entries[0].mapped_area.value == pytest.approx(1234.5)
