"""Textual presents immutable monitoring data without owning its interpretation."""

import asyncio
import datetime
import functools
import pathlib
import typing

import rich.json
import textual
import textual.app
import textual.binding
import textual.containers
import textual.widgets
import textual.widgets.tree

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.monitor.storage
import peri_scribe.monitor.theme
import peri_scribe.monitor.widgets
import peri_scribe.phases
from peri_scribe.units import units


POLL_INTERVAL = 500 * units.milliseconds


class MonitorApp(textual.app.App[None]):
    """The terminal observes log and report files without becoming a pipeline writer."""

    TITLE = "PeriScribe monitor"
    CSS = """
    /* A neutral edge prevents terminal margins from extending scrollbar colors. */
    Screen { padding-right: 1; }
    Header { background: $panel; color: $accent; }
    Tabs { background: $panel; }
    Tab.-active { background: $surface; color: $accent; text-style: bold; }
    Underline > .underline--bar { color: $accent; background: $panel; }
    #views { height: 1fr; }
    #activity { height: 2; padding: 0 1; color: $accent; }
    #phase-tree {
        width: 43%; min-width: 24; border-right: solid $border; background: $panel;
    }
    .filters { height: 3; }
    .search { width: 1fr; }
    .severity { width: 18; }
    .events { height: 1fr; }
    #run-table { height: 1fr; }
    #decisions { max-height: 4; padding: 0 1; overflow-y: auto; }
    #inspection { height: 6; border-top: solid $border; background: $panel; }
    #report-time { height: auto; padding: 1; color: $text-muted; }
    #report-viewer { height: 1fr; }
    #file-status { height: auto; max-height: 3; padding: 0 1; }
    """
    BINDINGS: typing.ClassVar[list[textual.binding.BindingType]] = [
        textual.binding.Binding("q", "quit", "Quit"),
        textual.binding.Binding("space", "toggle_follow", "Pause / follow"),
        textual.binding.Binding("end", "live", "Live", priority=True),
        textual.binding.Binding("slash", "search", "Search"),
        textual.binding.Binding("escape", "clear_filter", "Clear filter"),
        textual.binding.Binding("1", "view('pipeline')", "Pipeline", show=False),
        textual.binding.Binding("2", "view('logs')", "Logs", show=False),
        textual.binding.Binding("3", "view('runs')", "Runs", show=False),
        textual.binding.Binding("4", "view('report')", "Report", show=False),
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
        super().__init__()
        self.theme = peri_scribe.monitor.theme.DEFAULT_THEME
        self.year_directory = year_directory
        self.report_path = report_path
        self.branches = branches
        self.follower = peri_scribe.monitor.storage.Follower(year_directory / "logs")
        self.state = peri_scribe.monitor.model.State()
        self.visible_state = self.state
        self.selected_run = ""
        self.selected_phase: peri_scribe.phases.Path = ()
        self.following = True
        self.report = peri_scribe.monitor.storage.Report()
        self.archives: tuple[pathlib.Path, ...] = ()
        self.loaded_archives: set[pathlib.Path] = set()
        self.rows: dict[int, peri_scribe.monitor.events.Event] = {}
        self.tree_nodes: dict[
            peri_scribe.phases.Path,
            textual.widgets.tree.TreeNode[peri_scribe.monitor.model.PhaseView],
        ] = {}

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Provide four views over the same observer state.

        Yields:
            Navigation, pipeline hierarchy, events, run history, and current report.
        """
        yield textual.widgets.Header()
        yield textual.widgets.Static(id="activity", markup=False)
        with textual.widgets.TabbedContent(id="views"):
            with (
                textual.widgets.TabPane("Pipeline", id="pipeline"),
                textual.containers.Horizontal(),
            ):
                yield textual.widgets.Tree("All events", id="phase-tree")
                yield peri_scribe.monitor.widgets.Stream(id="pipeline-stream")
            with textual.widgets.TabPane("Logs", id="logs"):
                yield peri_scribe.monitor.widgets.Stream(id="log-stream")
            with textual.widgets.TabPane("Runs", id="runs"):
                yield textual.widgets.Button("Load older month", id="older")
                yield textual.widgets.DataTable(id="run-table", cursor_type="row")
            with textual.widgets.TabPane("Report", id="report"):
                yield textual.widgets.Static(id="report-time", markup=False)
                yield peri_scribe.monitor.widgets.ReportViewer(
                    open_links=False,
                    show_table_of_contents=False,
                    id="report-viewer",
                )
        yield textual.widgets.Static(id="decisions", markup=False)
        with textual.containers.VerticalScroll(id="inspection"):
            yield textual.widgets.Static(
                "Select an event to inspect its fields.",
                id="details",
                markup=False,
            )
        yield textual.widgets.Static(id="file-status", markup=False)
        yield textual.widgets.Footer()

    async def on_mount(self) -> None:
        """Load existing state before attaching the recurring read-only observer."""
        self.sub_title = str(self.year_directory)
        for table in self.query(peri_scribe.monitor.widgets.EventTable):
            table.add_columns("Time", "Level", "Event")
        self.query_one("#run-table", textual.widgets.DataTable).add_columns(
            "Started",
            "Command",
            "Outcome",
        )
        await self.refresh_files()
        self.set_interval(
            POLL_INTERVAL.m_as("seconds"),
            functools.partial(self.call_later, self.refresh_files),
        )

    def on_unmount(self) -> None:
        """Close retained log handles after the presentation exits."""
        self.follower.close()

    async def refresh_files(self) -> None:
        """Refresh log state and stable report snapshots independently of the tab."""
        batch = await asyncio.to_thread(self.follower.poll)
        if batch.records:
            self.state = await asyncio.to_thread(
                peri_scribe.monitor.model.append_records,
                self.state,
                batch.records,
            )
        report = await asyncio.to_thread(
            peri_scribe.monitor.storage.read_report,
            self.report_path,
            self.report,
        )
        if not self.is_running or not self.query("#views"):
            return
        self.archives = batch.archives
        self.query_one("#older", textual.widgets.Button).disabled = not any(
            path not in self.loaded_archives for path in self.archives
        )
        if batch.records:
            if self.following:
                self.visible_state = self.state
                self.selected_run = self.state.runs[-1].identifier
            self.render_state()
        elif not self.state.runs:
            self.render_state()
        run = self.current_run()
        pending = self.state.sequence - self.visible_state.sequence
        description = peri_scribe.monitor.presentation.activity(
            run,
            datetime.datetime.now(datetime.UTC),
        )
        mode = "FOLLOW" if self.following else f"PAUSED · {pending} new events"
        self.query_one("#activity", textual.widgets.Static).update(
            f"{mode} · {description}",
        )
        self.query_one("#file-status", textual.widgets.Static).update(
            "\n".join(batch.errors)
            or ("Waiting for logs" if not self.state.runs else ""),
        )
        self.query_one("#report-time", textual.widgets.Static).update(
            f"{self.report_path.name}\n{peri_scribe.monitor.presentation.report_heading(report)}",
        )
        if report != self.report:
            self.report = report
            viewer = self.query_one("#report-viewer", textual.widgets.MarkdownViewer)
            position = viewer.scroll_offset
            await viewer.document.update(report.content)
            if viewer.is_attached:
                viewer.scroll_to(position.x, position.y, animate=False)

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
        """Keep table positions stable while rendering updated projections."""
        run = self.current_run()
        projection = peri_scribe.monitor.model.phase_tree(run, self.branches)
        tree = self.query_one("#phase-tree", textual.widgets.Tree)
        previous = tree.scroll_offset
        expanded = {path: node.is_expanded for path, node in self.tree_nodes.items()}
        cursor = tree.cursor_node
        cursor_path = cursor.data.path if cursor is not None and cursor.data else ()
        tree.clear()
        self.tree_nodes.clear()
        for phase in projection.phases:
            parent = self.tree_nodes.get(phase.path[:-1], tree.root)
            self.tree_nodes[phase.path] = parent.add(
                peri_scribe.monitor.presentation.phase_label(phase),
                data=phase,
                expand=expanded.get(phase.path, True),
            )
        tree.root.expand()
        if cursor_path in self.tree_nodes:
            tree.call_after_refresh(tree.move_cursor, self.tree_nodes[cursor_path])
        tree.scroll_to(previous.x, previous.y, animate=False)
        if self.selected_phase not in self.tree_nodes:
            self.selected_phase = ()
        reasons = [
            *projection.reasons,
            *(
                f"Trimmed {omission.path[-1].phase}: {omission.reason}"
                for omission in projection.omissions
            ),
        ]
        self.query_one("#decisions", textual.widgets.Static).update("\n".join(reasons))
        self.rows.clear()
        for stream in self.query(peri_scribe.monitor.widgets.Stream):
            self.render_stream(stream, run)
        table = self.query_one("#run-table", textual.widgets.DataTable)
        row = table.cursor_row
        table.clear()
        for item in reversed(self.state.runs):
            table.add_row(
                *peri_scribe.monitor.presentation.run_cells(item),
                key=item.identifier,
            )
        table.move_cursor(row=row)

    def render_stream(
        self,
        stream: peri_scribe.monitor.widgets.Stream,
        run: peri_scribe.monitor.model.Run,
    ) -> None:
        """Use the same domain filter for both terminal log layouts.

        Args:
            stream: The terminal controls to populate.
            run: The selected domain run.
        """
        events = peri_scribe.monitor.model.filter_events(
            run,
            minimum_level=str(stream.query_one(textual.widgets.Select).value),
            query=stream.query_one(textual.widgets.Input).value,
            path=self.selected_phase if stream.id == "pipeline-stream" else (),
        )
        table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
        row = table.cursor_row
        position = table.scroll_offset
        table.clear()
        for event in events:
            self.rows[event.sequence] = event
            table.add_row(
                *peri_scribe.monitor.presentation.event_cells(event),
                key=str(event.sequence),
            )
        table.move_cursor(row=max(0, len(events) - 1) if self.following else row)
        if not self.following:
            table.scroll_to(position.x, position.y, animate=False)

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
            self.visible_state = self.state
            self.selected_run = str(event.row_key.value)
            self.selected_phase = ()
            self.action_view("pipeline")
            self.render_state()
        else:
            selected = self.rows[int(str(event.row_key.value))]
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
    def tab_changed(self, event: textual.widgets.TabbedContent.TabActivated) -> None:
        """Give report and run-history views their full available reading area.

        Args:
            event: The active terminal tab.
        """
        if not self.is_running:
            return
        show = event.pane.id in {"pipeline", "logs"}
        self.query_one("#inspection").display = show
        self.query_one("#decisions").display = show

    @textual.on(textual.widgets.Button.Pressed, "#older")
    async def load_older(self) -> None:
        """Load archived history independently of current log collection."""
        path = next(
            (path for path in self.archives if path not in self.loaded_archives),
            None,
        )
        if path is None:
            return
        batch = await asyncio.to_thread(peri_scribe.monitor.storage.read_archive, path)
        self.loaded_archives.add(path)
        current = sorted(
            (
                event
                for run in self.state.runs
                for event in peri_scribe.monitor.model.evidence(run)
            ),
            key=lambda event: event.sequence,
        )
        self.state = await asyncio.to_thread(
            peri_scribe.monitor.model.append_records,
            peri_scribe.monitor.model.State(),
            (*batch.records, *(dict(event.fields) for event in current)),
        )
        self.visible_state = self.state
        self.query_one("#file-status", textual.widgets.Static).update(
            "\n".join(batch.errors),
        )
        self.render_state()

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
        self.visible_state = self.state
        self.selected_run = self.state.runs[-1].identifier if self.state.runs else ""
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
