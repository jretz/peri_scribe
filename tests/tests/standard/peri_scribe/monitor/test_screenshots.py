"""Snapshots retain the visible terminal cells and use isolated local-time filenames."""

import datetime
import functools
import pathlib
import re
import unittest.mock

import pytest
import rich.text
import textual.widgets

import peri_scribe.monitor.app
import peri_scribe.monitor.screenshots
import tests.helpers.assertions.peri_scribe.monitor.screenshots
import tests.helpers.doubles.peri_scribe.monitor.screenshots
import tests.helpers.fixtures.peri_scribe.monitor.application
import tests.helpers.textual


@pytest.mark.parametrize("tab", ["pipeline", "logs", "runs", "report"])
@pytest.mark.asyncio
async def test_snapshot_screen_export_snapshot_preserves_screen_dimensions_and_styles(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
    tab: str,
) -> None:
    session = monitor_session
    await tests.helpers.textual.invoke(session.app.action_view, tab)
    await session.pilot.pause()
    screen = session.app.screen
    assert isinstance(screen, peri_scribe.monitor.screenshots.SnapshotScreen)
    await tests.helpers.textual.invoke(
        tests.helpers.assertions.peri_scribe.monitor.screenshots.assert_screen_matches_snapshot,
        screen,
    )


@pytest.mark.asyncio
async def test_snapshot_screen_export_snapshot_preserves_footer_during_binding_refresh(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    await tests.helpers.textual.invoke(session.app.action_view, "report")
    await session.pilot.pause()
    screen = session.app.screen
    assert isinstance(screen, peri_scribe.monitor.screenshots.SnapshotScreen)
    footer = session.app.query_one(textual.widgets.Footer)
    with unittest.mock.patch.object(
        footer,
        "mount_all",
        side_effect=functools.partial(
            tests.helpers.doubles.peri_scribe.monitor.screenshots.mount_after_snapshot_check,
            screen,
            footer.mount_all,
        ),
    ) as mount:
        await tests.helpers.textual.invoke(footer.call_later, footer.recompose)
        await session.pilot.pause()
    mount.assert_called()


@pytest.mark.asyncio
async def test_snapshot_screen_export_snapshot_preserves_unicode_and_scrolled_content(
    scrolling_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = scrolling_session
    await tests.helpers.textual.invoke(session.app.action_view, "report")
    await peri_scribe.monitor.app.render_report(session.app)
    await session.refresh()
    viewer = session.app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
    await tests.helpers.textual.scroll_end(viewer)
    await tests.helpers.textual.invoke(
        setattr,
        session.app,
        "title",
        "PeriScribe monitor · Café 火 🔥",
    )
    await session.refresh()
    screen = session.app.screen
    assert isinstance(screen, peri_scribe.monitor.screenshots.SnapshotScreen)
    content = rich.text.Text.from_ansi(
        await tests.helpers.textual.invoke(screen.export_snapshot),
    ).plain
    assert "Café 火 🔥" in content
    assert "Paragraph 99" in content
    assert "Paragraph 0" not in content


def test_save_snapshot_uses_local_whole_seconds_in_the_year_screenshots_directory(
    tmp_path: pathlib.Path,
) -> None:
    captured_at = datetime.datetime(2026, 9, 16, 2, 30, 5, 123456, tzinfo=datetime.UTC)
    path = peri_scribe.monitor.screenshots.save_snapshot(
        tmp_path / "2026",
        "\x1b[31mFire 火\x1b[0m\n",
        captured_at,
    )
    assert path.parent == tmp_path / "2026" / "screenshots"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}[+-]\d{4}\.txt", path.name)
    timestamp = datetime.datetime.strptime(path.stem, "%Y-%m-%d_%H-%M-%S%z")
    assert timestamp.replace(tzinfo=None) == captured_at.astimezone().replace(
        tzinfo=None,
        microsecond=0,
    )
    assert timestamp.utcoffset() == captured_at.astimezone().utcoffset()
    assert path.read_text(encoding="utf-8") == "\x1b[31mFire 火\x1b[0m\n"


def test_save_snapshot_preserves_existing_files_for_the_same_second(
    tmp_path: pathlib.Path,
) -> None:
    captured_at = datetime.datetime(2026, 9, 16, 2, 30, 5, tzinfo=datetime.UTC)
    path = peri_scribe.monitor.screenshots.save_snapshot(
        tmp_path,
        "original",
        captured_at,
    )
    with pytest.raises(FileExistsError):
        peri_scribe.monitor.screenshots.save_snapshot(
            tmp_path,
            "replacement",
            captured_at.replace(microsecond=500000),
        )
    assert path.read_text(encoding="utf-8") == "original"
