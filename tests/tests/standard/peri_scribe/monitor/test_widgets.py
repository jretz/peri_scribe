"""Report navigation distinguishes document anchors from external URLs."""

import typing
import unittest.mock

import pytest
import textual.widgets


if typing.TYPE_CHECKING:
    import tests.helpers.fixtures.peri_scribe.monitor.application


@pytest.mark.parametrize("href", ["#moonshine", "https://example.com/fire"])
def test_report_viewer_routes_links_without_loading_another_file(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    monkeypatch: pytest.MonkeyPatch,
    href: str,
) -> None:
    open_url = unittest.mock.Mock()
    monkeypatch.setattr(monitor_session.app, "open_url", open_url)
    monitor_session.app.report_path.write_text("# Report\n\n## Moonshine\n\nDetails")
    monitor_session.runner.run(monitor_session.app.refresh_files())
    viewer = monitor_session.app.query_one(textual.widgets.MarkdownViewer)
    monitor_session.call(
        viewer.document.post_message,
        textual.widgets.Markdown.LinkClicked(viewer.document, href),
    )
    monitor_session.runner.run(monitor_session.pilot.pause())
    assert viewer.document.source == monitor_session.app.report.content
    if href.startswith("#"):
        open_url.assert_not_called()
    else:
        open_url.assert_called_once_with(href)
