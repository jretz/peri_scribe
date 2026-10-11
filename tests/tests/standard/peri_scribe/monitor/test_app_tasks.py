"""Exercise overlapping public monitor operations independently of Textual's queue."""

import asyncio
import unittest.mock

import pytest
import textual.widgets

import peri_scribe.monitor.history
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import tests.helpers.doubles.peri_scribe.monitor.tasks
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.parametrize(
    ("stop", "cancel"),
    [(False, False), (False, True), (True, False), (True, True)],
)
@pytest.mark.asyncio
async def test_monitor_app_archive_and_refresh_preserve_owned_evidence(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stop: bool,
    cancel: bool,
) -> None:
    await tests.helpers.doubles.peri_scribe.monitor.tasks.application_replay(
        monitor_session.app,
        monkeypatch,
        stop=stop,
        cancel=cancel,
    )
    assert [
        run.identifier for run in monitor_session.app.controller.snapshot.records.runs
    ] == ([] if stop else ["archive", "new"])


@pytest.mark.asyncio
async def test_monitor_app_on_unmount_retains_descriptors_during_shared_lock_wait(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await tests.helpers.doubles.peri_scribe.monitor.tasks.shared_lock_replay(
        monitor_session.app,
        monkeypatch,
    )


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.asyncio
async def test_monitor_app_open_status_evidence_cannot_publish_after_unmount(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fails: bool,
) -> None:
    app = monitor_session.app
    previous = app.visible_state
    notification = unittest.mock.Mock()
    monkeypatch.setattr(app, "notify", notification)
    reading = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedCall(
        function=(
            unittest.mock.Mock(side_effect=OSError("unreadable"))
            if fails
            else peri_scribe.monitor.history.load_run
        ),
    )
    monkeypatch.setattr(peri_scribe.monitor.history, "load_run", reading)
    target = peri_scribe.monitor.status.evidence(
        tests.helpers.factories.peri_scribe.monitor.status.history(
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(),
        ),
    )[0]
    loading = asyncio.create_task(
        app.open_status_evidence(
            peri_scribe.monitor.status_widgets.OpenEvidence(target),
        ),
    )
    try:
        assert await asyncio.to_thread(reading.started.wait, 5)
        closing = asyncio.create_task(app.on_unmount())
        await app.controller.session.owner.stopped.wait()
        assert not closing.done()
    finally:
        reading.release.set()
    await asyncio.gather(loading, closing)
    assert app.visible_state is previous
    notification.assert_not_called()


@pytest.mark.asyncio
async def test_render_report_does_not_publish_completion_after_unmount(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = monitor_session.app
    await tests.helpers.textual.invoke(app.action_view, "report")
    await monitor_session.pilot.pause()
    app.report_path.write_text("# Newly observed report")
    document = app.query_one("#report-viewer", textual.widgets.MarkdownViewer).document
    update = tests.helpers.doubles.peri_scribe.monitor.tasks.PausedUpdate(
        function=document.update,
    )
    monkeypatch.setattr(document, "update", update)
    previous = app.rendered_report
    rendering = asyncio.create_task(app.controller.refresh())
    try:
        await asyncio.wait_for(update.started.wait(), 5)
        closing = asyncio.create_task(app.on_unmount())
        await app.controller.session.owner.stopped.wait()
        assert not closing.done()
    finally:
        update.release.set()
    await asyncio.gather(rendering, closing)
    assert app.rendered_report is previous
