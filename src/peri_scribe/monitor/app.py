"""Textual presents immutable monitoring data without owning its interpretation."""

import asyncio
import compression.zstd
import dataclasses
import datetime
import functools
import pathlib
import time
import typing

import rich.json
import textual
import textual.app
import textual.binding
import textual.containers
import textual.widgets
import textual.widgets.tree

import peri_scribe.monitor.changes
import peri_scribe.monitor.events
import peri_scribe.monitor.history
import peri_scribe.monitor.model
import peri_scribe.monitor.presentation
import peri_scribe.monitor.projection
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.storage
import peri_scribe.monitor.striping
import peri_scribe.monitor.theme
import peri_scribe.monitor.widgets
import peri_scribe.paths
import peri_scribe.phases
from measurement_units import units


POLL_INTERVAL = 500 * units.milliseconds


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
        self.follower = peri_scribe.monitor.storage.Follower(year_directory / "logs")
        self.history_reader = peri_scribe.monitor.history.Reader(
            year_directory / "logs",
        )
        self.files_changed = True
        self.reconcile_at = 0.0
        self.watching_stopped = asyncio.Event()
        self.status_snapshot: peri_scribe.monitor.projection.Snapshot | None = None
        self.state = peri_scribe.monitor.model.State()
        self.visible_state = self.state
        self.selected_run = ""
        self.selected_phase: peri_scribe.phases.Path = ()
        self.following = True
        self.report = peri_scribe.monitor.storage.Report()
        self.rendered_report = self.report
        self.report_rendering = asyncio.Lock()
        self.archives: tuple[pathlib.Path, ...] = ()
        self.loaded_archives: set[pathlib.Path] = set()
        self.rows: dict[int, peri_scribe.monitor.events.Event] = {}
        self.tree_nodes: dict[
            peri_scribe.phases.Path,
            textual.widgets.tree.TreeNode[peri_scribe.monitor.model.PhaseView],
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
        """Load existing state before attaching the recurring read-only observer."""
        self.sub_title = str(self.year_directory)
        for table in self.query(peri_scribe.monitor.widgets.EventTable):
            table.add_columns("Time", "Level", "Event")
        self.query_one("#run-table", textual.widgets.DataTable).add_columns(
            "Started",
            "Command",
            "Outcome",
        )
        self.run_worker(watch_files(self))
        await self.refresh_files()
        self.set_interval(
            POLL_INTERVAL.m_as("seconds"),
            functools.partial(self.call_later, refresh_clock, self),
        )

    def on_unmount(self) -> None:
        """Close retained log handles after the presentation exits."""
        self.watching_stopped.set()
        self.follower.close()
        self.history_reader.close()

    async def refresh_files(self) -> None:
        """Keep health live while reserving report work for its visible tab."""
        batch = await asyncio.to_thread(self.follower.poll)
        if batch.records:
            self.state = await asyncio.to_thread(
                peri_scribe.monitor.model.append_records,
                self.state,
                batch.records,
            )
        now = datetime.datetime.now(datetime.UTC)
        history = await asyncio.to_thread(self.history_reader.catch_up, now)
        files = await asyncio.to_thread(
            peri_scribe.monitor.status.read_files,
            self.year_directory,
            self.kmz_path,
            self.report_path,
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
        peri_scribe.monitor.widgets.update_content(
            self.query_one("#file-status", textual.widgets.Static),
            "\n".join(batch.errors)
            or ("Waiting for logs" if not self.state.runs else ""),
        )
        show_status(self, history, files, now)
        self.files_changed |= not batch.caught_up
        self.reconcile_at = (
            time.monotonic()
            + peri_scribe.monitor.changes.RECONCILE_INTERVAL.m_as("seconds")
        )
        await render_report(self)

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
        table = self.query_one("#run-table", peri_scribe.monitor.widgets.TintedTable)
        row = table.cursor_row
        table.clear()
        table.row_tints = tuple(
            peri_scribe.monitor.theme.RUN_TINTS.get(item.status)
            for item in reversed(self.state.runs)
        )
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
        table.row_tints = tuple(
            peri_scribe.monitor.theme.EVENT_TINTS.get(event.level) for event in events
        )
        for event in events:
            self.rows[event.sequence] = event
            table.add_row(
                *peri_scribe.monitor.presentation.event_cells(event),
                key=str(event.sequence),
            )
        table.move_cursor(row=max(0, len(events) - 1) if self.following else row)
        if not self.following:
            table.scroll_to(position.x, position.y, animate=False)

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
        target = message.target
        try:
            run = await asyncio.to_thread(
                peri_scribe.monitor.history.load_run,
                self.year_directory / "logs",
                target.run,
            )
        except (OSError, EOFError, compression.zstd.ZstdError) as error:
            self.notify(f"Unable to load run: {error}", severity="error")
            return
        if not run.events:
            self.notify(
                "The selected run's logs are no longer available",
                severity="warning",
            )
            return
        self.following = False
        self.selected_run = run.identifier
        self.visible_state = dataclasses.replace(
            self.state,
            runs=(
                *tuple(
                    item
                    for item in self.state.runs
                    if item.identifier != run.identifier
                ),
                run,
            ),
        )
        selected = next(
            (
                event
                for event in reversed(run.events)
                if event.fields == target.event.fields
            ),
            run.events[-1],
        )
        self.selected_phase = selected.path
        stream = self.query_one("#pipeline-stream", peri_scribe.monitor.widgets.Stream)
        stream.query_one(textual.widgets.Input).value = ""
        stream.query_one(textual.widgets.Select).value = "debug"
        self.action_view("pipeline")
        self.render_state()
        self.query_one("#details", textual.widgets.Static).update(
            rich.json.JSON(peri_scribe.monitor.presentation.details(selected)),
        )
        table = stream.query_one(peri_scribe.monitor.widgets.EventTable)
        table.move_cursor(row=table.get_row_index(str(selected.sequence)))
        table.focus()

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
        if event.pane.id == "report":
            await render_report(self)

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
        peri_scribe.monitor.widgets.update_content(
            self.query_one("#file-status", textual.widgets.Static),
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


async def watch_files(app: MonitorApp) -> None:
    """Coalesce notifications while the UI keeps ownership of file reads.

    Args:
        app: The observer collecting native change hints.
    """
    async for _ in peri_scribe.monitor.changes.watch(
        app.year_directory,
        app.watching_stopped,
    ):
        app.files_changed = True


async def refresh_clock(app: MonitorApp) -> None:
    """Advance ages independently of reads and reconcile native notifications.

    Args:
        app: The observer whose display and inputs may need refreshing.
    """
    if not app.is_running or not app.query("#views"):
        return
    if app.files_changed or time.monotonic() >= app.reconcile_at:
        app.files_changed = False
        await app.refresh_files()
    elif app.status_snapshot is not None:
        now = datetime.datetime.now(datetime.UTC)
        history = peri_scribe.monitor.history.append(
            app.history_reader.history,
            (),
            now,
        )
        app.history_reader.history = history
        show_status(app, history, app.status_snapshot.files, now)


def show_status(
    app: MonitorApp,
    history: peri_scribe.monitor.history.History,
    files: peri_scribe.monitor.status.Files,
    now: datetime.datetime,
) -> None:
    """Keep live metrics and the activity banner current without rereading files.

    Args:
        app: The observer presenting live status.
        history: Current health evidence.
        files: Latest observed artifact metadata.
        now: The current wall-clock time.
    """
    app.status_snapshot = peri_scribe.monitor.projection.refresh(
        history,
        files,
        now,
        app.status_snapshot,
    )
    app.query_one(peri_scribe.monitor.status_widgets.StatusPane).show_view(
        app.status_snapshot.view,
    )
    run = app.current_run()
    pending = app.state.sequence - app.visible_state.sequence
    description = peri_scribe.monitor.presentation.activity(
        run,
        datetime.datetime.now(datetime.UTC),
    )
    mode = "FOLLOW" if app.following else f"PAUSED · {pending} new events"
    peri_scribe.monitor.widgets.update_content(
        app.query_one("#activity", textual.widgets.Static),
        "LIVE STATUS · select an observation to inspect its Pipeline evidence"
        if app.query_one("#views", textual.widgets.TabbedContent).active == "status"
        else f"{mode} · {description}",
        layout=False,
    )


def report_visible(app: MonitorApp) -> bool:
    """Limit report work to a selected tab that remains mounted during file reads.

    Args:
        app: The terminal observer whose report may be selected.

    Returns:
        Whether its report tab is currently available and selected.
    """
    return bool(
        app.is_running
        and app.query("#views")
        and app.query_one("#views", textual.widgets.TabbedContent).active == "report",
    )


async def render_report(app: MonitorApp) -> None:
    """Read and render the visible report while preserving its reading position.

    Args:
        app: The terminal observer whose report is being read.
    """
    async with app.report_rendering:
        if not report_visible(app):
            return
        report = await asyncio.to_thread(
            peri_scribe.monitor.storage.read_report,
            app.report_path,
            app.report,
        )
        if not report_visible(app):
            return
        app.report = report
        if report == app.rendered_report:
            return
        app.query_one("#report-time", textual.widgets.Static).update(
            f"{app.report_path.name}\n{peri_scribe.monitor.presentation.report_heading(report)}",
        )
        viewer = app.query_one("#report-viewer", textual.widgets.MarkdownViewer)
        position = viewer.scroll_offset
        await viewer.document.update(report.content)
        app.rendered_report = report
        if viewer.is_attached:
            viewer.scroll_to(position.x, position.y, animate=False)
