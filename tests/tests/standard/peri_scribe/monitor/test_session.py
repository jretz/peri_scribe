"""Exercise framework-independent evidence, subscription, and resource ownership."""

import asyncio
import compression.zstd
import datetime
import json
import pathlib
import unittest.mock

import pytest
import time_machine

import peri_scribe.monitor.changes
import peri_scribe.monitor.history
import peri_scribe.monitor.session
import peri_scribe.monitor.storage
import tests.helpers.doubles.peri_scribe.monitor.session
import tests.helpers.factories.peri_scribe.monitor.events
from measurement_units import units


@pytest.mark.asyncio
async def test_monitor_session_start_loads_health_without_other_readers(
    monitor_year: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        tests.helpers.factories.peri_scribe.monitor.events.record("Starting command"),
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    with time_machine.travel("2026-09-16T08:01:00Z", tick=False):
        snapshot = await session.start(observe=False)
    assert snapshot.health is not None
    assert len(snapshot.history.state.runs) == 1
    assert not session.follower.started
    assert not snapshot.records.runs
    assert snapshot.report == peri_scribe.monitor.storage.Report()
    assert not session.observers
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_start_observes_once_and_closes_observers(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "watch",
        tests.helpers.doubles.peri_scribe.monitor.session.hints,
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    await session.start()
    observers = session.observers
    await session.start()
    assert session.observers == observers
    await session.close()
    assert all(task.done() for task in observers)
    await session.start()
    assert session.observers == observers


@pytest.mark.asyncio
async def test_monitor_session_close_reports_observer_failure_after_cleanup(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "watch",
        unittest.mock.AsyncMock(side_effect=OSError("observer failed")),
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    subscription = session.subscribe()
    await session.start()
    with pytest.raises(ExceptionGroup, match="Monitor observation failed") as failure:
        await session.close()
    assert len(failure.value.exceptions) == 1
    assert str(failure.value.exceptions[0]) == "observer failed"
    assert session.owner.closed.is_set()
    assert await subscription.receive() is None
    assert all(task.done() for task in session.observers)


@pytest.mark.asyncio
async def test_monitor_session_subscribe_coalesces_complete_versions(
    monitor_year: pathlib.Path,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    first = session.subscribe()
    second = session.subscribe()
    initial = await first.receive()
    assert initial is session.snapshot
    await session.request(peri_scribe.monitor.session.RefreshRecords())
    latest = await session.request(peri_scribe.monitor.session.RefreshReport())
    assert await first.receive() is latest
    assert await second.receive() is latest
    expected_version = 2
    assert latest.version == expected_version
    assert initial is not None
    assert initial.version == 0
    first.close()
    assert first not in session.subscriptions
    assert await first.receive() is None
    await session.close()
    assert await second.receive() is None
    assert await session.subscribe().receive() is None


@pytest.mark.asyncio
async def test_subscription_iteration_finishes_for_waiting_consumer(
    monitor_year: pathlib.Path,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    subscription = session.subscribe()
    assert aiter(subscription) is subscription
    assert await anext(subscription) is session.snapshot
    waiting = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)
    subscription.close()
    with pytest.raises(StopAsyncIteration):
        await waiting
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_request_prioritizes_queued_work_without_preemption(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="active")),
    )
    await gate.started.wait()
    background = asyncio.create_task(
        session.request(
            peri_scribe.monitor.session.LoadRun(identifier="background"),
            priority=peri_scribe.monitor.session.Priority.BACKGROUND,
        ),
    )
    immediate = asyncio.create_task(
        session.request(
            peri_scribe.monitor.session.LoadRun(identifier="immediate"),
            priority=peri_scribe.monitor.session.Priority.IMMEDIATE,
        ),
    )
    following = asyncio.create_task(
        session.request(
            peri_scribe.monitor.session.LoadRun(identifier="following"),
            priority=peri_scribe.monitor.session.Priority.IMMEDIATE,
        ),
    )
    await tests.helpers.doubles.peri_scribe.monitor.session.queued(session, 3)
    assert gate.requests == ["active"]
    gate.released.set()
    await asyncio.gather(active, background, immediate, following)
    assert gate.requests == ["active", "immediate", "following", "background"]
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_promote_reuses_identity_and_changes_admission_order(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active_request = peri_scribe.monitor.session.LoadRun(identifier="active")
    active = asyncio.create_task(session.request(active_request))
    await gate.started.wait()
    ordinary = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="ordinary")),
    )
    request = peri_scribe.monitor.session.LoadRun(identifier="promoted")
    promoted = asyncio.create_task(
        session.request(
            request,
            priority=peri_scribe.monitor.session.Priority.BACKGROUND,
        ),
    )
    await tests.helpers.doubles.peri_scribe.monitor.session.queued(session, 2)
    assert not session.promote(active_request)
    assert not session.promote(
        peri_scribe.monitor.session.LoadRun(identifier="promoted"),
    )
    assert session.promote(request)
    assert not session.promote(request)
    gate.released.set()
    await asyncio.gather(active, ordinary, promoted)
    assert gate.requests == ["active", "promoted", "ordinary"]
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_request_cancels_queued_work_without_execution(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="active")),
    )
    await gate.started.wait()
    queued = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="cancelled")),
    )
    await tests.helpers.doubles.peri_scribe.monitor.session.queued(session, 1)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    gate.released.set()
    await active
    assert gate.requests == ["active"]
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_request_settles_admitted_work_despite_cancellation(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="active")),
    )
    await gate.started.wait()
    for _ in range(3):
        active.cancel()
        await asyncio.sleep(0)
    assert not active.done()
    assert session.owner.lock.locked()
    gate.released.set()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert session.snapshot.errors == ("active",)
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_request_preserves_admission_after_failure(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate(
        failures=frozenset({"failed"}),
    )
    gate.released.set()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    with pytest.raises(RuntimeError, match="request failed"):
        await session.request(peri_scribe.monitor.session.LoadRun(identifier="failed"))
    await session.request(peri_scribe.monitor.session.LoadRun(identifier="success"))
    assert session.snapshot.version == 1
    assert session.snapshot.errors == ("success",)
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_close_rejects_late_publication_and_retires_once(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        tests.helpers.factories.peri_scribe.monitor.events.record("Starting command"),
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    before = await session.request(peri_scribe.monitor.session.RefreshRecords())
    stream = next(iter(session.follower.cursors.values())).stream
    gate = tests.helpers.doubles.peri_scribe.monitor.session.Gate()
    monkeypatch.setattr(peri_scribe.monitor.session, "execute", gate.execute)
    active = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="active")),
    )
    await gate.started.wait()
    queued = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="queued")),
    )
    await tests.helpers.doubles.peri_scribe.monitor.session.queued(session, 1)
    cancelled = asyncio.create_task(
        session.request(peri_scribe.monitor.session.LoadRun(identifier="cancelled")),
    )
    await tests.helpers.doubles.peri_scribe.monitor.session.queued(session, 2)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    closing = asyncio.create_task(session.close())
    await session.owner.stopped.wait()
    assert not stream.closed
    assert not closing.done()
    assert await queued is before
    for _ in range(3):
        closing.cancel()
        await asyncio.sleep(0)
    gate.released.set()
    assert await active is before
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert stream.closed
    assert session.snapshot is before
    await session.close()
    assert await session.request(peri_scribe.monitor.session.RefreshRecords()) is before


@pytest.mark.asyncio
async def test_monitor_session_request_loads_records_archives_and_selected_evidence(
    monitor_year: pathlib.Path,
) -> None:
    record = tests.helpers.factories.peri_scribe.monitor.events.record
    current = tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        record("Starting command", run_id="current"),
    )
    archive = current.parent / "2026-08.jsonl.zst"
    archive.write_bytes(
        compression.zstd.compress(
            (json.dumps(record("Starting command", run_id="archived")) + "\n").encode(),
        ),
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    latest = await session.request(peri_scribe.monitor.session.RefreshRecords())
    assert [run.identifier for run in latest.records.runs] == ["current"]
    assert latest.archives == (archive,)
    older = await session.request(peri_scribe.monitor.session.LoadOlder())
    assert [run.identifier for run in older.records.runs] == ["archived", "current"]
    assert older.loaded_archives == frozenset({archive})
    assert await session.request(peri_scribe.monitor.session.LoadOlder()) is older
    selected = await session.request(
        peri_scribe.monitor.session.LoadRun(identifier="archived"),
    )
    assert selected.evidence is not None
    assert selected.evidence.identifier == "archived"
    assert selected.records is older.records
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_request_distinguishes_missing_run_and_failed_read(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    missing = await session.request(
        peri_scribe.monitor.session.LoadRun(identifier="gone"),
    )
    assert missing.evidence is not None
    assert not missing.evidence.events
    monkeypatch.setattr(
        peri_scribe.monitor.history,
        "load_run",
        unittest.mock.Mock(side_effect=OSError("unreadable")),
    )
    failed = await session.request(
        peri_scribe.monitor.session.LoadRun(identifier="gone"),
    )
    assert failed.evidence is None
    assert failed.errors == ("Unable to load run: unreadable",)
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_tick_refreshes_requested_records_and_report(
    monitor_year: pathlib.Path,
) -> None:
    report = monitor_year / "report.md"
    report.write_text("initial")
    session = peri_scribe.monitor.session.MonitorSession(monitor_year, report)
    await session.start(observe=False)
    await session.request(peri_scribe.monitor.session.RefreshRecords())
    await session.request(peri_scribe.monitor.session.RefreshReport())
    report.write_text("replaced")
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        tests.helpers.factories.peri_scribe.monitor.events.record("Starting command"),
    )
    session.files_changed = True
    await session.tick()
    assert session.snapshot.report.content == "replaced"
    assert len(session.snapshot.records.runs) == 1
    await session.close()


@pytest.mark.asyncio
async def test_monitor_session_tick_preserves_requested_component_boundaries(
    monitor_year: pathlib.Path,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    await session.tick()
    assert session.snapshot.health is not None
    assert not session.follower.started
    assert not session.report_requested
    await session.close()


@pytest.mark.asyncio
async def test_advance_clock_expires_health_without_advancing_file_cursors(
    monitor_year: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.monitor.events.write_log(
        monitor_year,
        tests.helpers.factories.peri_scribe.monitor.events.record("Starting command"),
    )
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    assert await session.request(peri_scribe.monitor.session.AdvanceClock()) is (
        session.snapshot
    )
    with time_machine.travel("2026-09-16T08:01:00Z", tick=False) as clock:
        initial = await session.start(observe=False)
        unchanged = await session.request(peri_scribe.monitor.session.AdvanceClock())
        assert unchanged is initial
        cursor = next(iter(session.history_reader.follower.cursors.values())).stream
        position = cursor.tell()
        clock.shift(datetime.timedelta(hours=49))
        await session.tick()
        assert session.snapshot.history.state.runs == ()
        assert cursor.tell() == position
    await session.close()


@pytest.mark.asyncio
async def test_refresh_records_requests_reconciliation_for_an_unfinished_batch(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    session.files_changed = False
    monkeypatch.setattr(
        session.follower,
        "poll",
        unittest.mock.Mock(
            return_value=peri_scribe.monitor.storage.Batch(
                errors=("retry",),
                caught_up=False,
            ),
        ),
    )
    snapshot = await session.request(peri_scribe.monitor.session.RefreshRecords())
    assert session.files_changed
    assert snapshot.errors == ("retry",)
    await session.close()


@pytest.mark.asyncio
async def test_watch_records_native_change_hints(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    session.files_changed = False
    monkeypatch.setattr(
        peri_scribe.monitor.changes,
        "watch",
        tests.helpers.doubles.peri_scribe.monitor.session.changes,
    )
    await peri_scribe.monitor.session.watch(session)
    assert session.files_changed
    await session.close()


@pytest.mark.asyncio
async def test_clock_reconciles_after_interval_and_obeys_shutdown(
    monitor_year: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = peri_scribe.monitor.session.MonitorSession(
        monitor_year,
        monitor_year / "report.md",
    )
    tick = unittest.mock.AsyncMock(side_effect=session.watching_stopped.set)
    monkeypatch.setattr(session, "tick", tick)
    monkeypatch.setattr(
        peri_scribe.monitor.session,
        "CLOCK_INTERVAL",
        1 * units.microseconds,
    )
    async with asyncio.timeout(5):
        await peri_scribe.monitor.session.clock(session)
    tick.assert_awaited_once()
    await session.close()
