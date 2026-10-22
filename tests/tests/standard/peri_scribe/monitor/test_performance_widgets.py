"""Deferred chart updates remain safe before terminal controls are mounted."""

import unittest.mock

import pytest

import peri_scribe.monitor.performance
import peri_scribe.monitor.performance_widgets
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.application


def test_performance_pane_show_view_retains_evidence_before_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = peri_scribe.monitor.performance_widgets.PerformancePane()
    render = unittest.mock.Mock()
    monkeypatch.setattr(peri_scribe.monitor.performance, "render", render)
    observed_at = tests.helpers.factories.peri_scribe.monitor.status.NOW
    pane.show_view((), observed_at)
    pane.on_resize()
    assert pane.series == ()
    assert pane.observed_at == observed_at
    render.assert_not_called()


@pytest.mark.asyncio
async def test_performance_pane_redraw_ignores_detached_controls(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    pane = monitor_session.app.query_one(
        peri_scribe.monitor.performance_widgets.PerformancePane,
    )
    await pane.remove()
    pane.redraw()
