"""Terminal snapshots preserve the composed screen for later replay with cat."""

import asyncio
import datetime
import functools
import pathlib
import typing

import textual.app
import textual.screen


class SnapshotScreen(textual.screen.Screen[None]):
    """The screen owns access to Textual's final, clipped rendering of its widgets."""

    def export_snapshot(self) -> str:
        """Preserve terminal cells and styles without cursor-positioning sequences.

        Returns:
            ANSI-colored screen rows with terminal styles reset before and after them.
        """
        rows = self._compositor.render_strips()
        return (
            "\x1b[0m"
            + "\n".join(row.render(self.app.console) for row in rows)
            + "\x1b[0m\n"
        )


def save_snapshot(
    year_directory: pathlib.Path,
    content: str,
    captured_at: datetime.datetime,
) -> pathlib.Path:
    """Keep screenshots together and retain existing files if timestamps collide.

    Args:
        year_directory: The year directory being observed.
        content: The rendered terminal screen, including ANSI color codes.
        captured_at: The capture time whose local representation names the file.

    Returns:
        The newly written snapshot's path.
    """
    directory = year_directory / "screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = captured_at.astimezone().strftime("%Y-%m-%d_%H-%M-%S%z")
    path = directory / f"{timestamp}.txt"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return path


class SnapshotApp(textual.app.App[None]):
    """Share snapshot palette integration without mixing it into monitor controls."""

    def __init__(self, year_directory: pathlib.Path) -> None:
        """Keep saved screens beside the observed year's data.

        Args:
            year_directory: The year directory being observed.
        """
        super().__init__()
        self.year_directory = year_directory

    @typing.override
    def get_default_screen(self) -> SnapshotScreen:
        """Use a screen that can preserve the monitor's composed terminal cells.

        Returns:
            The monitor's main screen.
        """
        return SnapshotScreen()

    @typing.override
    def get_system_commands(
        self,
        screen: textual.screen.Screen,
    ) -> typing.Iterable[textual.app.SystemCommand]:
        """Expose terminal snapshots alongside Textual's standard palette commands.

        Args:
            screen: The screen from which the command palette was opened.

        Yields:
            Built-in commands and a screenshot command for the monitor screen.
        """
        yield from (
            command
            for command in super().get_system_commands(screen)
            if command.title != "Screenshot"
        )
        if isinstance(screen, SnapshotScreen):
            yield textual.app.SystemCommand(
                "Take screenshot",
                "Save ANSI-colored text in the year's screenshots directory",
                functools.partial(self.call_after_refresh, self.save_snapshot, screen),
            )

    async def save_snapshot(
        self,
        screen: SnapshotScreen,
    ) -> None:
        """Capture after the palette closes and report filesystem failures in the UI.

        Args:
            screen: The monitor screen whose layout has finished refreshing.
        """
        content = screen.export_snapshot()
        captured_at = datetime.datetime.now(datetime.UTC)
        try:
            path = await asyncio.to_thread(
                save_snapshot,
                self.year_directory,
                content,
                captured_at,
            )
        except OSError as error:
            self.notify(f"Unable to save screenshot: {error}", severity="error")
        else:
            self.notify(f"Screenshot saved to {path}")
