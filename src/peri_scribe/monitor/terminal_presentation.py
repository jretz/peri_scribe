"""Apply controller requests to the terminal's concrete controls."""

import collections.abc
import dataclasses
import typing

import textual.widgets

import peri_scribe.monitor.display
import peri_scribe.monitor.health_presentation
import peri_scribe.monitor.model
import peri_scribe.monitor.rendering
import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.storage
import peri_scribe.monitor.terminal_contract
import peri_scribe.monitor.widgets


type Host = peri_scribe.monitor.terminal_contract.Host
type Filters = tuple[
    peri_scribe.monitor.display.Filter,
    peri_scribe.monitor.display.Filter,
]


class Presentation(typing.Protocol):
    """Keep terminal mutation separate from evidence scheduling and authorization."""

    def available(self, app: Host) -> bool:
        """Return whether the terminal still accepts presentation."""
        ...

    def after_refresh(
        self,
        app: Host,
        callback: collections.abc.Callable[[], None],
    ) -> None:
        """Admit a callback only after the current terminal frame."""
        ...

    def older_enabled(self, app: Host, *, enabled: bool) -> None:
        """Expose whether another archive remains available."""
        ...

    def health(
        self,
        app: Host,
        view: peri_scribe.monitor.health_presentation.View,
    ) -> None:
        """Present the actual immutable health projection."""
        ...

    def activity(self, app: Host) -> None:
        """Present the current live or paused inspection description."""
        ...

    def errors(self, app: Host, errors: tuple[str, ...]) -> None:
        """Present current domain read errors."""
        ...

    def filters(self, app: Host) -> Filters:
        """Return the current immutable controls in pipeline/log order."""
        ...

    async def records(
        self,
        app: Host,
        prepared: peri_scribe.monitor.display.Records,
        generation: int,
    ) -> None:
        """Apply prepared records while preserving the controller's authorization."""
        ...

    def has_report(self, app: Host) -> bool:
        """Return whether the report viewer remains attached."""
        ...

    async def report(
        self,
        app: Host,
        report: peri_scribe.monitor.storage.Report,
    ) -> None:
        """Apply the actual observed Markdown and its file identity."""
        ...

    async def evidence(
        self,
        app: Host,
        run: peri_scribe.monitor.model.Run,
        target: peri_scribe.monitor.status.Target,
    ) -> None:
        """Apply exact requested evidence to the diagnostic controls."""
        ...

    def cursor(self, app: Host, name: str) -> None:
        """Reveal the retained diagnostic cursor after its layout has completed."""
        ...


@dataclasses.dataclass(frozen=True, kw_only=True)
class Widgets(Presentation):
    """Delegate presentation to the actual mounted Textual controls."""

    @typing.override
    def available(self, app: Host) -> bool:
        """Return whether the running app still owns its views."""
        return bool(app.is_running and app.query("#views"))

    @typing.override
    def after_refresh(
        self,
        app: Host,
        callback: collections.abc.Callable[[], None],
    ) -> None:
        """Use the framework's actual completed-frame callback."""
        app.call_after_refresh(callback)

    @typing.override
    def older_enabled(self, app: Host, *, enabled: bool) -> None:
        """Update the real archive control."""
        app.query_one("#older", textual.widgets.Button).disabled = not enabled

    @typing.override
    def health(
        self,
        app: Host,
        view: peri_scribe.monitor.health_presentation.View,
    ) -> None:
        """Apply health through the existing native Status pane."""
        app.query_one(peri_scribe.monitor.status_widgets.StatusPane).show_view(view)

    @typing.override
    def activity(self, app: Host) -> None:
        """Delegate activity formatting and mutation unchanged."""
        peri_scribe.monitor.rendering.show_activity(app)

    @typing.override
    def errors(self, app: Host, errors: tuple[str, ...]) -> None:
        """Keep the native literal file-status presentation."""
        peri_scribe.monitor.widgets.update_content(
            app.query_one("#file-status", textual.widgets.Static),
            "\n".join(errors),
        )

    @typing.override
    def filters(self, app: Host) -> Filters:
        """Read both real stream controls in their original order.

        Returns:
            The current pipeline and full-log filters.
        """
        filters = []
        for identifier in ("pipeline-stream", "log-stream"):
            stream = app.query_one(f"#{identifier}", peri_scribe.monitor.widgets.Stream)
            filters.append(
                peri_scribe.monitor.display.Filter(
                    minimum_level=str(stream.query_one(textual.widgets.Select).value),
                    query=stream.query_one(textual.widgets.Input).value,
                    path=app.selected_phase if identifier == "pipeline-stream" else (),
                ),
            )
        return filters[0], filters[1]

    @typing.override
    async def records(
        self,
        app: Host,
        prepared: peri_scribe.monitor.display.Records,
        generation: int,
    ) -> None:
        """Keep native batching and stale-generation checks unchanged."""
        await peri_scribe.monitor.rendering.apply_records(app, prepared, generation)

    @typing.override
    def has_report(self, app: Host) -> bool:
        """Read the current native report attachment.

        Returns:
            Whether the real report viewer remains attached.
        """
        return bool(app.query("#report-viewer"))

    @typing.override
    async def report(
        self,
        app: Host,
        report: peri_scribe.monitor.storage.Report,
    ) -> None:
        """Keep native Markdown update and scroll preservation unchanged."""
        await peri_scribe.monitor.rendering.apply_report(app, report)

    @typing.override
    async def evidence(
        self,
        app: Host,
        run: peri_scribe.monitor.model.Run,
        target: peri_scribe.monitor.status.Target,
    ) -> None:
        """Keep native evidence navigation and exact row selection unchanged."""
        await peri_scribe.monitor.rendering.inspect_evidence(app, run, target)

    @typing.override
    def cursor(self, app: Host, name: str) -> None:
        """Use the existing real diagnostic cursor adjustment."""
        peri_scribe.monitor.rendering.reveal_diagnostic_cursor(app, name)
