"""Mount real controls with only the neighboring widgets their behavior requires."""

import collections.abc
import contextlib
import typing
import unittest.mock

import textual.app
import textual.containers
import textual.timer
import textual.widgets

import peri_scribe.monitor.widgets


@contextlib.contextmanager
def delayed_frames() -> collections.abc.Generator[None]:
    """Hold automatic screen frames while input handlers request layout changes.

    Other timers keep running. Resuming the held timers on exit schedules their work
    without painting synchronously, so a subsequent refresh must await the geometry.

    Yields:
        An input interval whose frame timers resume even if an action fails.
    """
    timers: set[textual.timer.Timer] = set()
    resume = textual.timer.Timer.resume

    def defer(timer: textual.timer.Timer) -> None:
        """Keep only screen updates from racing ahead of the test's refresh.

        Args:
            timer: The timer being resumed by the mounted widget.
        """
        if timer.name == "screen_update":
            timer.pause()
            timers.add(timer)
        else:
            resume(timer)

    try:
        with unittest.mock.patch.object(textual.timer.Timer, "resume", defer):
            yield
    finally:
        for timer in timers:
            resume(timer)


class DividerApp(textual.app.App[None]):
    """Both orientations exercise layout and pointer capture in a small terminal."""

    CSS = """
    #views { height: 1fr; min-height: 8; }
    #before { width: 43fr; min-width: 24; }
    #after { width: 57fr; min-width: 24; }
    #inspection { height: 6; min-height: 3; }
    """

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Provide resizable neighbors without unrelated monitor controls.

        Yields:
            Horizontal and vertical dividers with visible panes on each side.
        """
        views = textual.containers.Horizontal(id="views")
        inspection = textual.widgets.Static(id="inspection")
        with views:
            before = textual.widgets.Static(id="before")
            after = textual.widgets.Static(id="after")
            yield before
            yield peri_scribe.monitor.widgets.PaneDivider(
                before,
                after,
                dimension=peri_scribe.monitor.widgets.Dimension.WIDTH,
                identifier="pipeline-divider",
            )
            yield after
        yield peri_scribe.monitor.widgets.PaneDivider(
            views,
            inspection,
            dimension=peri_scribe.monitor.widgets.Dimension.HEIGHT,
            identifier="inspection-divider",
        )
        yield inspection


class ReportViewerApp(textual.app.App[None]):
    """Link routing needs a mounted Markdown document, without filesystem polling."""

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Supply an anchor that distinguishes local navigation from external links.

        Yields:
            The real report viewer with a small document.
        """
        yield peri_scribe.monitor.widgets.ReportViewer(
            "# Report\n\n## Moonshine\n\nDetails",
            open_links=False,
            show_table_of_contents=False,
        )
