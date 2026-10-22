"""Fit terminal performance charts to the available reading area."""

import datetime
import typing

import textual.app
import textual.containers
import textual.widgets

import peri_scribe.monitor.performance
import peri_scribe.monitor.widgets


class PerformancePane(textual.containers.VerticalScroll):
    """Keep charts scrollable while current evidence and terminal dimensions change."""

    DEFAULT_CSS = """
    PerformancePane { padding: 1; }
    #performance-charts { height: auto; text-wrap: nowrap; }
    """

    def __init__(self) -> None:
        """Retain prepared samples so resizing needs no additional evidence read."""
        super().__init__(id="performance-pane")
        self.series: tuple[peri_scribe.monitor.performance.Series, ...] = ()
        self.observed_at = datetime.datetime.now(datetime.UTC)

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Use literal chart text so command names cannot become terminal markup.

        Yields:
            The complete set of charts inside one scrollable reading area.
        """
        yield textual.widgets.Static(
            "Loading performance…",
            id="performance-charts",
            markup=False,
        )

    def show_view(
        self,
        series: tuple[peri_scribe.monitor.performance.Series, ...],
        now: datetime.datetime,
    ) -> None:
        """Replace chart data without resetting the reader's scroll position.

        Args:
            series: Durations grouped by execution mode from recent structural evidence.
            now: The observation time used to select the samples.
        """
        self.series = series
        self.observed_at = now
        self.redraw()

    def on_resize(self) -> None:
        """Redraw the same evidence at the terminal's current width."""
        self.redraw()

    def redraw(self) -> None:
        """Keep labels and chart cells within the space left by the scrollbar."""
        if self.is_attached:
            peri_scribe.monitor.widgets.update_content(
                self.query_one("#performance-charts", textual.widgets.Static),
                peri_scribe.monitor.performance.render(
                    self.series,
                    self.observed_at,
                    max(24, self.scrollable_content_region.width),
                ),
            )
