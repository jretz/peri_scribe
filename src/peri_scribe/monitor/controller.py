"""Translate observable domain snapshots into independently prepared terminal content.

Algorithm reasoning and contracts:
[Monitor presentation](../../../docs/algorithms/monitor-presentation.md)
"""

import asyncio
import dataclasses
import datetime

import textual.widgets

import peri_scribe.monitor.display
import peri_scribe.monitor.health_presentation
import peri_scribe.monitor.rendering
import peri_scribe.monitor.session
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.tasks
import peri_scribe.monitor.terminal_contract
import peri_scribe.monitor.widgets


type ContentRequest = (
    peri_scribe.monitor.session.RefreshRecords
    | peri_scribe.monitor.session.RefreshReport
)


@dataclasses.dataclass(kw_only=True)
class ContentWork:
    """Share content admission between background preparation and user navigation."""

    request: ContentRequest
    priority: peri_scribe.monitor.session.Priority
    task: asyncio.Task[None] = dataclasses.field(init=False)


class Controller:
    """Own presentation scheduling without making the domain depend on its consumer."""

    def __init__(self, app: peri_scribe.monitor.terminal_contract.Host) -> None:
        """Keep rendering lifetimes separate from the session's reader ownership.

        Args:
            app: The terminal adapter receiving prepared content.
        """
        self.app = app
        self.session = peri_scribe.monitor.session.MonitorSession(
            app.year_directory,
            app.report_path,
        )
        self.snapshot = self.session.snapshot
        self.subscription = self.session.subscribe()
        self.stopped = False
        self.presented = False
        self.diagnostics_requested = False
        self.generation = 0
        self.prepared_generation = 0
        self.display_task: asyncio.Task[None] | None = None
        self.listener: asyncio.Task[None] | None = None
        self.background: asyncio.Task[None] | None = None
        self.cosmetic_task: asyncio.Task[None] | None = None
        self.cosmetic_changed = asyncio.Event()
        self.content: dict[type[ContentRequest], ContentWork] = {}
        self.report_lock = asyncio.Lock()

    async def start(self) -> None:
        """Publish complete health before allowing other content preparation."""
        self.listener = asyncio.create_task(self.listen())
        await self.session.start()
        await self.accept(self.session.snapshot)
        self.cosmetic_task = asyncio.create_task(self.watch_presentation())
        self.app.call_after_refresh(self.begin_background)

    async def listen(self) -> None:
        """Consume coalesced snapshots on the terminal's event loop."""
        async for snapshot in self.subscription:
            await self.accept(snapshot)

    async def accept(self, snapshot: peri_scribe.monitor.session.Snapshot) -> None:
        """Keep domain revisions and inspection state consistent through refreshes.

        Args:
            snapshot: A complete domain publication, possibly superseding queued work.
        """
        if not self.available() or snapshot.version <= self.snapshot.version:
            return
        previous = self.snapshot
        self.snapshot = snapshot
        app = self.app
        if snapshot.records is not previous.records:
            if app.following:
                app.visible_state = snapshot.records
                app.selected_run = (
                    snapshot.records.runs[-1].identifier
                    if snapshot.records.runs
                    else ""
                )
            self.schedule_display()
        app.query_one("#older", textual.widgets.Button).disabled = not any(
            path not in snapshot.loaded_archives for path in snapshot.archives
        )
        if snapshot.health is not previous.health:
            self.show_health(datetime.datetime.now(datetime.UTC))
            self.cosmetic_changed.set()
        peri_scribe.monitor.rendering.show_activity(app)
        peri_scribe.monitor.widgets.update_content(
            app.query_one("#file-status", textual.widgets.Static),
            "\n".join(snapshot.errors),
        )
        if self.presented and snapshot.report != previous.report:
            await self.render_report()

    def show_health(self, now: datetime.datetime) -> None:
        """Redraw elapsed ages without changing the session's evidence or version.

        Args:
            now: The current presentation clock observation.
        """
        if self.available() and self.snapshot.health is not None:
            self.app.query_one(
                peri_scribe.monitor.status_widgets.StatusPane,
            ).show_view(
                peri_scribe.monitor.health_presentation.prepare(
                    self.snapshot.health,
                    now,
                ),
            )

    async def watch_presentation(self) -> None:
        """Keep cosmetic durations current without scheduling evidence collection."""
        while not self.stopped:
            self.cosmetic_changed.clear()
            now = datetime.datetime.now(datetime.UTC)
            deadline = (
                peri_scribe.monitor.health_presentation.deadline(
                    self.snapshot.health,
                    now,
                )
                if self.snapshot.health is not None
                else None
            )
            try:
                await asyncio.wait_for(
                    self.cosmetic_changed.wait(),
                    max(0, (deadline - now).total_seconds()) if deadline else None,
                )
            except TimeoutError:
                if self.available():
                    self.show_health(datetime.datetime.now(datetime.UTC))
                    peri_scribe.monitor.rendering.show_activity(self.app)

    def available(self) -> bool:
        """Keep callbacks from publishing into a detached terminal.

        Returns:
            Whether the terminal still accepts presentation updates.
        """
        return bool(
            not self.stopped and self.app.is_running and self.app.query("#views"),
        )

    def begin_background(self) -> None:
        """Begin preparation after the complete initial Status frame was painted."""
        if self.available() and not self.presented:
            self.presented = True
            self.background = asyncio.create_task(self.prepare_remaining())

    async def prepare_remaining(self) -> None:
        """Warm diagnostic records and the report without delaying the initial frame."""
        snapshot = await self.prepare_content(
            peri_scribe.monitor.session.RefreshRecords(),
            priority=peri_scribe.monitor.session.Priority.BACKGROUND,
        )
        await self.accept(snapshot)
        self.schedule_display()
        await self.flush_display()
        snapshot = await self.prepare_content(
            peri_scribe.monitor.session.RefreshReport(),
            priority=peri_scribe.monitor.session.Priority.BACKGROUND,
        )
        await self.accept(snapshot)
        await self.render_report()

    async def prepare_content(
        self,
        request: ContentRequest,
        *,
        priority: peri_scribe.monitor.session.Priority,
        refresh: bool = False,
    ) -> peri_scribe.monitor.session.Snapshot:
        """Join content already requested and promote work still waiting for admission.

        Args:
            request: The independently prepared content required by this caller.
            priority: The caller's admission precedence.
            refresh: Whether completed content must be read again.

        Returns:
            The complete snapshot from the shared content request.
        """
        work = self.content.get(type(request))
        if work is None or (refresh and work.task.done()):
            work = ContentWork(request=request, priority=priority)
            self.content[type(request)] = work
            work.task = asyncio.create_task(load_content(self.session, work))
        elif priority < work.priority:
            work.priority = priority
            self.session.promote(work.request, priority=priority)
        await peri_scribe.monitor.tasks.settle(work.task)
        return self.session.snapshot

    def schedule_display(self, *, requested: bool = False) -> None:
        """Coalesce preparations while preserving the most recent user controls.

        Args:
            requested: Whether explicit navigation requires content before first paint.
        """
        self.diagnostics_requested |= requested
        self.generation += 1
        if (
            self.available()
            and (self.presented or self.diagnostics_requested)
            and (self.display_task is None or self.display_task.done())
        ):
            if self.display_task is not None:
                self.display_task.result()
            self.display_task = asyncio.create_task(self.prepare_display())

    async def prepare_display(self) -> None:
        """Reject obsolete preparation and leave widget mutation on the UI thread."""
        while self.available() and self.prepared_generation != self.generation:
            generation = self.generation
            app = self.app
            run = app.current_run()
            filters = []
            for identifier in ("pipeline-stream", "log-stream"):
                stream = app.query_one(
                    f"#{identifier}",
                    peri_scribe.monitor.widgets.Stream,
                )
                filters.append(
                    peri_scribe.monitor.display.Filter(
                        minimum_level=str(
                            stream.query_one(textual.widgets.Select).value,
                        ),
                        query=stream.query_one(textual.widgets.Input).value,
                        path=app.selected_phase
                        if identifier == "pipeline-stream"
                        else (),
                    ),
                )
            prepared = await asyncio.to_thread(
                peri_scribe.monitor.display.prepare,
                self.snapshot.records,
                run,
                app.branches,
                *filters,
            )
            if not self.available():
                return
            if generation != self.generation:
                continue
            await peri_scribe.monitor.rendering.apply_records(app, prepared, generation)
            if generation == self.generation:
                self.prepared_generation = generation

    async def flush_display(self) -> None:
        """Let explicit user requests await the preparation already in flight."""
        while (task := self.display_task) is not None:
            await peri_scribe.monitor.tasks.settle(task)
            if self.display_task is task:
                return

    async def activate(self, name: str) -> None:
        """Promote requested content while reusing the session's queued work.

        Args:
            name: The terminal tab selected by the user.
        """
        if not self.available() or name == "status":
            return
        request = (
            peri_scribe.monitor.session.RefreshReport()
            if name == "report"
            else peri_scribe.monitor.session.RefreshRecords()
        )
        snapshot = await self.prepare_content(
            request,
            priority=peri_scribe.monitor.session.Priority.IMMEDIATE,
        )
        await self.accept(snapshot)
        if name == "report":
            await self.render_report()
        else:
            self.schedule_display(requested=True)
            await self.flush_display()

    async def refresh(self) -> None:
        """Request a fresh domain snapshot for explicit refresh commands."""
        snapshot = await self.session.request(
            peri_scribe.monitor.session.RefreshHealth(),
        )
        await self.accept(snapshot)
        if self.presented:
            snapshot = await self.prepare_content(
                peri_scribe.monitor.session.RefreshRecords(),
                priority=peri_scribe.monitor.session.Priority.NORMAL,
                refresh=True,
            )
            await self.accept(snapshot)
            snapshot = await self.prepare_content(
                peri_scribe.monitor.session.RefreshReport(),
                priority=peri_scribe.monitor.session.Priority.NORMAL,
                refresh=True,
            )
            await self.accept(snapshot)
            await self.flush_display()
            await self.render_report()

    async def load_older(self) -> None:
        """Request historical evidence without exposing archive readers to widgets."""
        snapshot = await self.session.request(peri_scribe.monitor.session.LoadOlder())
        await self.accept(snapshot)
        if self.available():
            self.app.visible_state = self.snapshot.records
            self.schedule_display()
            await self.flush_display()

    async def open_evidence(self, target: peri_scribe.monitor.status.Target) -> None:
        """Resolve historical evidence before updating the terminal's selection.

        Args:
            target: The immutable observation selected from Status.
        """
        snapshot = await self.session.request(
            peri_scribe.monitor.session.LoadRun(identifier=target.run),
            priority=peri_scribe.monitor.session.Priority.IMMEDIATE,
        )
        await self.accept(snapshot)
        if not self.available():
            return
        run = snapshot.evidence
        if run is None:
            self.app.notify("\n".join(snapshot.errors), severity="error")
        elif not run.events:
            self.app.notify(
                "The selected run's logs are no longer available",
                severity="warning",
            )
        else:
            await peri_scribe.monitor.rendering.inspect_evidence(self.app, run, target)

    async def render_report(self) -> None:
        """Serialize Markdown updates and reject obsolete completion checkpoints."""
        async with self.report_lock:
            while self.available() and self.snapshot.report != self.app.rendered_report:
                report = self.snapshot.report
                await peri_scribe.monitor.rendering.apply_report(self.app, report)
                if not self.available() or not self.app.query("#report-viewer"):
                    return

    async def close(self) -> None:
        """Detach notifications before waiting for data and presentation workers."""
        self.stopped = True
        self.cosmetic_changed.set()
        self.subscription.close()
        try:
            await self.session.close()
        finally:
            await self.finish()

    async def finish(self) -> None:
        """Settle presentation tasks even when domain shutdown reports a failure."""
        tasks = tuple(
            task
            for task in (
                self.listener,
                self.background,
                self.display_task,
                self.cosmetic_task,
                *(work.task for work in self.content.values()),
            )
            if task is not None
        )
        if tasks:
            await peri_scribe.monitor.tasks.settle(
                asyncio.create_task(finish_presentations(tasks)),
            )


async def load_content(
    session: peri_scribe.monitor.session.MonitorSession,
    work: ContentWork,
) -> None:
    """Read admission priority when the task starts, including immediate promotion.

    Args:
        session: The scheduler that owns content collection.
        work: The content identity shared by all interested callers.

    Completed work retains no obsolete snapshot; its callers observe the session's
    latest complete version after joining.
    """
    await session.request(work.request, priority=work.priority)


async def finish_presentations(tasks: tuple[asyncio.Task[object], ...]) -> None:
    """Observe preparation completion before the terminal releases its controls.

    Args:
        tasks: Already admitted presentation work, each guarded against late updates.

    Raises:
        BaseExceptionGroup: All task failures after every peer has settled.
    """
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [result for result in results if isinstance(result, BaseException)]
    if failures:
        message = "Monitor presentation tasks failed"
        raise BaseExceptionGroup(message, failures)
