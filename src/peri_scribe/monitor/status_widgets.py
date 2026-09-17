"""Live health stays readable and navigable without changing the selected log run."""

import typing

import rich.text
import textual.app
import textual.containers
import textual.events
import textual.message
import textual.widgets

import peri_scribe.monitor.status
import peri_scribe.monitor.theme
import peri_scribe.monitor.widgets


COLORS = {
    peri_scribe.monitor.status.Health.GOOD: peri_scribe.monitor.theme.GREEN,
    peri_scribe.monitor.status.Health.ACTIVE: peri_scribe.monitor.theme.CYAN,
    peri_scribe.monitor.status.Health.WARNING: peri_scribe.monitor.theme.YELLOW,
    peri_scribe.monitor.status.Health.BAD: peri_scribe.monitor.theme.RED,
}
SYMBOLS = {
    peri_scribe.monitor.status.Health.GOOD: "✓",
    peri_scribe.monitor.status.Health.ACTIVE: ">",
    peri_scribe.monitor.status.Health.WARNING: "!",
    peri_scribe.monitor.status.Health.BAD: "✗",
}


class OpenEvidence(textual.message.Message):
    """A health observation requests the exact run and event supporting its status."""

    def __init__(self, target: peri_scribe.monitor.status.Target) -> None:
        """Carry stable identity across file refreshes.

        Args:
            target: The recorded observation selected by the viewer.
        """
        super().__init__()
        self.target = target


def metric_text(metric: peri_scribe.monitor.status.Metric) -> rich.text.Text:
    """Literal text prevents source names and exceptions from becoming markup.

    Args:
        metric: The health observation to present.

    Returns:
        A colored label and value with a navigation hint when evidence is available.
    """
    text = rich.text.Text(
        f"{SYMBOLS[metric.health]} {metric.label}",
        style=f"bold {COLORS[metric.health]}",
    )
    if metric.target:
        text.append("  ↗ Pipeline", style="dim")
    text.append("\n" + metric.text, style=COLORS[metric.health])
    return text


class StatusLink(textual.widgets.Static, can_focus=True):
    """Whole observations support both pointer and keyboard navigation."""

    DEFAULT_CSS = """
    StatusLink {
        height: auto; padding: 1 1 0 1; margin-bottom: 1;
        border-top: solid $foreground 15%;
    }
    StatusLink:focus { background: $panel; text-style: bold; }
    """

    def __init__(self, identifier: str) -> None:
        """Keep stable widget identities while their live values change.

        Args:
            identifier: The observation's terminal selector.
        """
        super().__init__(id=identifier, markup=False)
        self.target: peri_scribe.monitor.status.Target | None = None

    def show_metric(self, metric: peri_scribe.monitor.status.Metric) -> None:
        """Update color and navigation together so clicks always match the text.

        Args:
            metric: The current live observation.
        """
        self.target = metric.target
        self.update(metric_text(metric))
        self.tooltip = "Open this evidence in Pipeline" if self.target else None

    def on_click(self) -> None:
        """Make the visible observation its own navigation target."""
        if self.target:
            self.post_message(OpenEvidence(self.target))

    def on_key(self, event: textual.events.Key) -> None:
        """Provide the same drill-down without requiring mouse support.

        Args:
            event: The key pressed while this observation is focused.
        """
        if event.key == "enter":
            self.on_click()
            event.stop()


class StatusPane(textual.containers.VerticalScroll):
    """Stable controls preserve focus and scroll while health updates in real time."""

    DEFAULT_CSS = """
    StatusPane { padding: 1; }
    StatusPane .status-heading {
        height: auto; margin: 1 1; padding-top: 1; text-style: bold;
        border-top: solid $foreground 15%;
    }
    #status-overview { height: auto; padding: 1; background: $panel; margin-bottom: 1; }
    #status-outputs { height: auto; }
    #status-outputs StatusLink { width: 1fr; border-top: none; padding-top: 0; }
    #status-kmz { margin-right: 1; border-right: solid $foreground 15%; }
    #status-coverage { height: auto; margin: 0 1 1 1; }
    #status-exceptions { height: auto; max-height: 16; }
    #status-recent, #status-transitions { height: auto; max-height: 9; }
    """

    def __init__(self) -> None:
        """Maintain only presentation caches; the parent owns live evidence."""
        super().__init__(id="status-content")
        self.view: peri_scribe.monitor.status.View | None = None
        self.targets: dict[tuple[str, str], peri_scribe.monitor.status.Target] = {}

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Keep the freshness and current work visible before historical details.

        Yields:
            Live observations, exception groups, and concise change history.
        """
        yield textual.widgets.Static(id="status-overview", markup=False)
        with textual.containers.Horizontal(id="status-outputs"):
            yield StatusLink("status-kmz")
            yield StatusLink("status-report")
        for name in ("activity", "source", "publication", "failure"):
            yield StatusLink(f"status-{name}")
        yield textual.widgets.Static(
            "Exceptions · last 48 hours",
            classes="status-heading",
        )
        yield textual.widgets.Static(id="status-coverage", markup=False)
        yield peri_scribe.monitor.widgets.TintedTable(
            id="status-exceptions",
            cursor_type="row",
        )
        yield textual.widgets.Static(
            "Recent outcomes · select a run to inspect",
            classes="status-heading",
        )
        yield peri_scribe.monitor.widgets.TintedTable(
            id="status-recent",
            cursor_type="row",
        )
        yield textual.widgets.Static("Recent transitions", classes="status-heading")
        yield peri_scribe.monitor.widgets.TintedTable(
            id="status-transitions",
            cursor_type="row",
        )

    def on_mount(self) -> None:
        """Column identities stay fixed while their observations are refreshed."""
        self.query_one("#status-exceptions", textual.widgets.DataTable).add_columns(
            "Exception / phase",
            "Count",
            "Runs",
            "First / latest",
            "Outcome",
        )
        for name in ("recent", "transitions"):
            self.query_one(f"#status-{name}", textual.widgets.DataTable).add_columns(
                "Time",
                "Observation",
            )

    def update_table(
        self,
        name: str,
        metrics: tuple[peri_scribe.monitor.status.Metric, ...],
    ) -> None:
        """Preserve a selected observation when newer rows arrive above it.

        Args:
            name: The recent-outcome or transition table.
            metrics: Its current ordered observations.
        """
        table = self.query_one(
            f"#status-{name}",
            peri_scribe.monitor.widgets.TintedTable,
        )
        selected = (
            table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if table.row_count
            else None
        )
        position = table.scroll_offset
        table.clear()
        table.row_tints = tuple(COLORS[metric.health] for metric in metrics)
        for index, metric in enumerate(metrics):
            key = (
                f"{metric.target.run}:{metric.target.event.sequence}"
                if metric.target
                else str(index)
            )
            table.add_row(
                metric.label,
                rich.text.Text(
                    f"{SYMBOLS[metric.health]} {metric.text}",
                    style=COLORS[metric.health],
                ),
                key=key,
            )
            if metric.target:
                self.targets[name, key] = metric.target
        if selected is not None and selected in table.rows:
            table.move_cursor(row=table.get_row_index(selected))
        table.scroll_to(position.x, position.y, animate=False)

    def show_view(self, view: peri_scribe.monitor.status.View) -> None:
        """Refresh live ages even while the Pipeline tab is browsing a past run.

        Args:
            view: The current immutable health projection.
        """
        self.query_one("#status-overview", textual.widgets.Static).update(
            metric_text(view.overview),
        )
        for name, metric in zip(
            ("kmz", "report", "activity", "source", "publication", "failure"),
            view.metrics,
            strict=True,
        ):
            self.query_one(f"#status-{name}", StatusLink).show_metric(metric)
        self.query_one("#status-coverage", textual.widgets.Static).update(
            metric_text(view.coverage),
        )
        for name, metrics in (
            ("recent", view.recent),
            ("transitions", view.transitions),
        ):
            if self.view is None or getattr(self.view, name) != metrics:
                self.targets = {
                    key: value for key, value in self.targets.items() if key[0] != name
                }
                self.update_table(name, metrics)
        if self.view is None or self.view.exceptions != view.exceptions:
            self.show_exceptions(view.exceptions)
        self.view = view

    def show_exceptions(
        self,
        groups: tuple[peri_scribe.monitor.status.ExceptionSummary, ...],
    ) -> None:
        """Keep each count attached to its latest instance when group order changes.

        Args:
            groups: Current exception groups in recency order.
        """
        table = self.query_one(
            "#status-exceptions",
            peri_scribe.monitor.widgets.TintedTable,
        )
        selected = (
            table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if table.row_count
            else None
        )
        position = table.scroll_offset
        table.clear()
        self.targets = {
            key: value for key, value in self.targets.items() if key[0] != "exceptions"
        }
        table.row_tints = tuple(COLORS[group.health] for group in groups)
        for group in groups:
            key = group.description + "\n" + group.path
            table.add_row(
                rich.text.Text(key, style=COLORS[group.health]),
                str(group.occurrences),
                str(len(group.runs)),
                peri_scribe.monitor.status.local_time(group.first)
                + "\n"
                + peri_scribe.monitor.status.local_time(group.latest.event.timestamp),
                rich.text.Text(
                    f"{SYMBOLS[group.health]} {group.outcome}",
                    style=COLORS[group.health],
                ),
                key=key,
                height=2,
            )
            self.targets["exceptions", key] = group.latest
        if not groups:
            table.add_row(
                "No exceptions observed in available history",
                "",
                "",
                "",
                "",
                key="empty",
            )
        if selected is not None and selected in table.rows:
            table.move_cursor(row=table.get_row_index(selected))
        table.scroll_to(position.x, position.y, animate=False)

    @textual.on(textual.widgets.DataTable.RowSelected)
    def select_evidence(self, event: textual.widgets.DataTable.RowSelected) -> None:
        """Status selections must not be interpreted as ordinary log-table row IDs.

        Args:
            event: The selected status row.
        """
        event.stop()
        name = str(event.data_table.id).removeprefix("status-")
        target = self.targets.get((name, str(event.row_key.value)))
        if target:
            self.post_message(OpenEvidence(target))
