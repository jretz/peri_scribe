"""Exercise screenshot creation through the monitor's real command palette."""

import datetime
import typing
import unittest.mock

import rich.text
import textual.command
import textual.screen

import peri_scribe.monitor.screenshots


if typing.TYPE_CHECKING:
    import tests.helpers.fixtures.peri_scribe.monitor.application
    import tests.helpers.fixtures.peri_scribe.monitor.screenshots


def test_snapshot_app_get_system_commands_replaces_svg_with_ansi_screenshot(
    snapshot_session: tests.helpers.fixtures.peri_scribe.monitor.screenshots.Session,
) -> None:
    app = snapshot_session.app
    commands = list(app.get_system_commands(app.screen))
    titles = {command.title for command in commands}
    assert {"Theme", "Quit", "Keys", "Take screenshot"} <= titles
    assert "Screenshot" not in titles


def test_snapshot_app_get_system_commands_excludes_snapshots_on_other_screens(
    snapshot_session: tests.helpers.fixtures.peri_scribe.monitor.screenshots.Session,
) -> None:
    commands = snapshot_session.app.get_system_commands(textual.screen.Screen())
    assert not {"Screenshot", "Take screenshot"} & {
        command.title for command in commands
    }


def test_snapshot_app_save_snapshot_from_palette_captures_monitor_after_palette_closes(
    monitor_session: tests.helpers.fixtures.peri_scribe.monitor.application.Session,
) -> None:
    session = monitor_session
    before = datetime.datetime.now().astimezone().replace(microsecond=0)
    session.runner.run(session.pilot.press("ctrl+p"))
    assert isinstance(session.app.screen, textual.command.CommandPalette)
    session.runner.run(session.pilot.press(*"Take screenshot"))
    session.runner.run(session.pilot.pause())
    with unittest.mock.patch.object(session.app, "notify") as notify:
        session.runner.run(session.pilot.press("enter"))
        session.runner.run(session.pilot.pause())
    after = datetime.datetime.now().astimezone()
    assert not isinstance(session.app.screen, textual.command.CommandPalette)
    paths = list((session.directory / "screenshots").glob("*.txt"))
    assert len(paths) == 1
    assert (
        before
        <= datetime.datetime.strptime(paths[0].stem, "%Y-%m-%d_%H-%M-%S%z")
        <= after
    )
    content = paths[0].read_text(encoding="utf-8")
    assert "PeriScribe monitor" in rich.text.Text.from_ansi(content).plain
    assert "Take screenshot" not in content
    assert "Screenshot saved" not in content
    assert "\x1b[" in content
    notify.assert_called_once_with(f"Screenshot saved to {paths[0]}")


def test_snapshot_app_save_snapshot_reports_write_failure_without_exiting(
    snapshot_session: tests.helpers.fixtures.peri_scribe.monitor.screenshots.Session,
) -> None:
    session = snapshot_session
    (session.app.year_directory / "screenshots").write_text(
        "Not a directory",
        encoding="utf-8",
    )
    screen = session.app.screen
    assert isinstance(screen, peri_scribe.monitor.screenshots.SnapshotScreen)
    with unittest.mock.patch.object(session.app, "notify") as notify:
        session.runner.run(session.app.save_snapshot(screen))
    assert session.app.is_running
    assert notify.call_args.kwargs["severity"] == "error"
    assert "Unable to save screenshot" in notify.call_args.args[0]
