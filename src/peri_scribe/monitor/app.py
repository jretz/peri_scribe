"""Textual presents immutable monitoring data without owning its interpretation.

Algorithm reasoning and contracts:
[Monitor evidence](../../../docs/algorithms/monitor-evidence.md)
[Worker lifetimes](../../../docs/algorithms/worker-lifetimes.md)
"""

import pathlib
import typing

import rich.json
import textual
import textual.app
import textual.binding
import textual.containers
import textual.widgets
import textual.widgets.tree

import peri_scribe.monitor.controller
import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.monitor.rendering
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.storage
import peri_scribe.monitor.striping
import peri_scribe.monitor.theme
import peri_scribe.monitor.widgets
import peri_scribe.paths
import peri_scribe.phases


class MonitorApp(peri_scribe.monitor.striping.StripedApp):
    """The terminal observes log and report files without becoming a pipeline writer."""

    TITLE = "PeriScribe monitor"
    CSS = """
    /* A neutral edge prevents terminal margins from extending scrollbar colors. */
    Screen { padding-right: 1; }
    Header { background: $panel; color: $accent; }
    Tabs { background: $panel; }
    Tab.-active { background: $surface; color: $accent; text-style: bold; }
    Underline > .underline--bar { color: $accent; background: $panel; }
    #views { height: 1fr; min-height: 8; }
    #activity { height: 2; padding: 0 1; color: $accent; }
    #phase-tree {
        width: 43fr; min-width: 20%; background: $panel;
    }
    #pipeline-stream { width: 57fr; min-width: 20%; }
    .filters { height: 3; }
    .search { width: 1fr; }
    .severity { width: 18; }
    .events { height: 1fr; }
    #run-table { height: 1fr; }
    #decisions { max-height: 4; padding: 0 1; overflow-y: auto; }
    #inspection { height: 6; min-height: 3; background: $panel; }
    #report-time { height: auto; padding: 1; color: $text-muted; }
    #report-viewer { height: 1fr; }
    #file-status { height: auto; max-height: 3; padding: 0 1; }
    """
    BINDINGS: typing.ClassVar[list[textual.binding.BindingType]] = [
        textual.binding.Binding("q", "quit", "Quit"),
        textual.binding.Binding("ctrl+d", "quit", "Quit", show=False, priority=True),
        textual.binding.Binding("space", "toggle_follow", "Pause / follow"),
        textual.binding.Binding("end", "live", "Live", priority=True),
        textual.binding.Binding("slash", "search", "Search"),
        textual.binding.Binding("escape", "clear_filter", "Clear filter"),
        textual.binding.Binding("1", "view('status')", "Status", show=False),
        textual.binding.Binding("2", "view('pipeline')", "Pipeline", show=False),
        textual.binding.Binding("3", "view('logs')", "Logs", show=False),
        textual.binding.Binding("4", "view('runs')", "Runs", show=False),
        textual.binding.Binding("5", "view('report')", "Report", show=False),
    ]

    def __init__(
        self,
        year_directory: pathlib.Path,
        report_path: pathlib.Path,
        branches: peri_scribe.phases.Branches,
    ) -> None:
        """Inject filesystem locations and catalogue instances into the adapter.

        Args:
            year_directory: The observed year's data directory.
            report_path: The report path resolved by the existing report module.
            branches: Configured feed and source names.
        """
        super().__init__(year_directory)
        self.scroll_sensitivity_y = 1.0
        self.theme = peri_scribe.monitor.theme.DEFAULT_THEME
        self.report_path = report_path
        self.kmz_path = peri_scribe.paths.kmz_path(year_directory)
        self.branches = branches
        self.visible_state = peri_scribe.monitor.model.State()
        self.selected_run = ""
        self.selected_phase: peri_scribe.phases.Path = ()
        self.following = True
        self.rendered_report = peri_scribe.monitor.storage.Report()
        self.controller = peri_scribe.monitor.controller.Controller(self)
        self.rows: dict[
            textual.widgets.DataTable,
            dict[str, peri_scribe.monitor.events.Event],
        ] = {}
        self.tree_nodes: dict[
            peri_scribe.phases.Path,
            textual.widgets.tree.TreeNode[peri_scribe.monitor.model.PhaseState],
        ] = {}

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Provide live health and four diagnostic views over the same evidence.

        Yields:
            Navigation, pipeline hierarchy, events, run history, and current report.
        """
        yield textual.widgets.Header()
        yield textual.widgets.Static(id="activity", markup=False)
        views = textual.widgets.TabbedContent(id="views")
        inspection = textual.containers.VerticalScroll(id="inspection")
        with views:
            with textual.widgets.TabPane("Status", id="status"):
                yield peri_scribe.monitor.status_widgets.StatusPane()
            with (
                textual.widgets.TabPane("Pipeline", id="pipeline"),
                textual.containers.Horizontal(),
            ):
                tree = textual.widgets.Tree("All events", id="phase-tree")
                stream = peri_scribe.monitor.widgets.Stream(id="pipeline-stream")
                yield tree
                yield peri_scribe.monitor.widgets.PaneDivider(
                    tree,
                    stream,
                    dimension=peri_scribe.monitor.widgets.Dimension.WIDTH,
                    identifier="pipeline-divider",
                )
                yield stream
            with textual.widgets.TabPane("Logs", id="logs"):
                yield peri_scribe.monitor.widgets.Stream(id="log-stream")
            with textual.widgets.TabPane("Runs", id="runs"):
                yield textual.widgets.Button("Load older month", id="older")
                yield peri_scribe.monitor.widgets.TintedTable(
                    id="run-table",
                    cursor_type="row",
                )
            with textual.widgets.TabPane("Report", id="report"):
                yield textual.widgets.Static(id="report-time", markup=False)
                yield peri_scribe.monitor.widgets.ReportViewer(
                    open_links=False,
                    show_table_of_contents=False,
                    id="report-viewer",
                )
        yield textual.widgets.Static(id="decisions", markup=False)
        yield peri_scribe.monitor.widgets.PaneDivider(
            views,
            inspection,
            dimension=peri_scribe.monitor.widgets.Dimension.HEIGHT,
            identifier="inspection-divider",
        )
        with inspection:
            yield textual.widgets.Static(
                "Select an event to inspect its fields.",
                id="details",
                markup=False,
            )
        yield textual.widgets.Static(id="file-status", markup=False)
        yield textual.widgets.Footer()

    async def on_mount(self) -> None:
        """Attach presentation to the observable session after controls exist."""
        self.sub_title = str(self.year_directory)
        for table in self.query(peri_scribe.monitor.widgets.EventTable):
            table.add_columns("Time", "Level", "Event")
        self.query_one("#run-table", textual.widgets.DataTable).add_columns(
            "Started",
            "Command",
            "Outcome",
        )
        await self.controller.start()

    async def on_unmount(self) -> None:
        """Detach presentation and settle admitted work before releasing controls."""
        await self.controller.close()

    async def refresh_files(self) -> None:
        """Forward an explicit refresh request to the presentation controller."""
        await self.controller.refresh()

    def current_run(self) -> peri_scribe.monitor.model.Run:
        """Keep a stable selection when the observer is paused or looking at history.

        Returns:
            The selected run or a pending pipeline when no logs exist yet.
        """
        return next(
            (
                run
                for run in self.visible_state.runs
                if run.identifier == self.selected_run
            ),
            self.visible_state.runs[-1]
            if self.visible_state.runs
            else peri_scribe.monitor.model.Run(identifier="waiting", command="run"),
        )

    def render_state(self) -> None:
        """Schedule preparation from the latest controls without blocking input."""
        self.controller.schedule_display()

    @textual.on(peri_scribe.monitor.status_widgets.OpenEvidence)
    async def open_status_evidence(
        self,
        message: peri_scribe.monitor.status_widgets.OpenEvidence,
    ) -> None:
        """Load the selected run and focus the precise evidence behind a health value.

        Args:
            message: The live observation selected in Status.
        """
        message.stop()
        await self.controller.open_evidence(message.target)

    @textual.on(textual.widgets.Tree.NodeSelected, "#phase-tree")
    def select_phase(self, event: textual.widgets.Tree.NodeSelected) -> None:
        """Only started phases may become a filter; waiting nodes remain inert.

        Args:
            event: The selected tree node.
        """
        phase = event.node.data
        if (
            phase is not None
            and phase.status == peri_scribe.monitor.model.Status.WAITING
        ):
            return
        self.selected_phase = phase.path if phase else ()
        self.render_state()

    @textual.on(textual.widgets.DataTable.RowSelected)
    def select_row(self, event: textual.widgets.DataTable.RowSelected) -> None:
        """Translate run and event selections into stable domain identities.

        Args:
            event: The user's selected table row.
        """
        if event.data_table.id == "run-table":
            self.following = False
            self.visible_state = self.controller.snapshot.records
            self.selected_run = str(event.row_key.value)
            self.selected_phase = ()
            self.action_view("pipeline")
            self.render_state()
        else:
            selected = self.rows.get(event.data_table, {}).get(str(event.row_key.value))
            if selected is not None:
                self.query_one("#details", textual.widgets.Static).update(
                    rich.json.JSON(peri_scribe.monitor.presentation.details(selected)),
                )

    @textual.on(textual.widgets.Input.Changed)
    @textual.on(textual.widgets.Select.Changed)
    def filter_changed(self) -> None:
        """Reapply domain filtering after a terminal filter control changes."""
        if self.is_running and self.query("#phase-tree"):
            self.render_state()

    @textual.on(peri_scribe.monitor.widgets.EventTable.Browse)
    def pause_browsing(self) -> None:
        """Freeze the visible snapshot while file collection continues."""
        self.following = False

    @textual.on(textual.widgets.TabbedContent.TabActivated, "#views")
    async def tab_changed(
        self,
        event: textual.widgets.TabbedContent.TabActivated,
    ) -> None:
        """Give report and run-history views their full available reading area.

        Args:
            event: The active terminal tab.
        """
        if not self.is_running:
            return
        show = event.pane.id in {"pipeline", "logs"}
        self.query_one("#inspection").display = show
        self.query_one("#inspection-divider").display = show
        self.query_one("#decisions").display = show
        peri_scribe.monitor.rendering.show_activity(self)
        self.run_worker(self.controller.activate(event.pane.id or "status"))

    @textual.on(textual.widgets.Button.Pressed, "#older")
    async def load_older(self) -> None:
        """Load archived history independently of current log collection."""
        await self.controller.load_older()

    def action_view(self, name: str) -> None:
        """Expose direct keyboard navigation without coupling tab names to domain data.

        Args:
            name: The requested terminal tab.
        """
        self.query_one("#views", textual.widgets.TabbedContent).active = name

    def action_toggle_follow(self) -> None:
        """Pause or catch up without discarding newly collected records."""
        if self.following:
            self.following = False
        else:
            self.action_live()

    def action_live(self) -> None:
        """Return both log views to the newest retained command and event."""
        self.following = True
        self.visible_state = self.controller.snapshot.records
        self.selected_run = (
            self.controller.snapshot.records.runs[-1].identifier
            if self.controller.snapshot.records.runs
            else ""
        )
        self.selected_phase = ()
        self.render_state()

    def action_search(self) -> None:
        """Focus full-width log search for quick keyboard investigation."""
        self.action_view("logs")
        self.query_one("#log-stream", peri_scribe.monitor.widgets.Stream).query_one(
            textual.widgets.Input,
        ).focus()

    def action_clear_filter(self) -> None:
        """Remove phase and text restrictions without changing the observed run."""
        self.selected_phase = ()
        for field in self.query(textual.widgets.Input):
            field.value = ""
        self.render_state()
