"""Describe terminal capabilities without coupling presentation to its concrete app."""

import collections.abc
import pathlib
import typing

import textual.css.query
import textual.widget
import textual.widgets
import textual.widgets.tree

import peri_scribe.monitor.events
import peri_scribe.monitor.model
import peri_scribe.monitor.session
import peri_scribe.monitor.storage


if typing.TYPE_CHECKING:
    import peri_scribe.phases


class Preparation(typing.Protocol):
    """Widget application only needs committed data and preparation authorization."""

    @property
    def snapshot(self) -> peri_scribe.monitor.session.Snapshot:
        """The latest domain version accepted by the presentation owner."""
        ...

    @property
    def generation(self) -> int:
        """The revision that authorizes prepared widget updates."""
        ...

    def available(self) -> bool:
        """Return whether the terminal still accepts prepared updates."""
        ...

    def schedule_display(self, *, requested: bool = False) -> None:
        """Prepare current controls without requiring the concrete scheduler.

        Args:
            requested: Whether explicit navigation requires immediate preparation.
        """
        ...

    async def flush_display(self) -> None:
        """Wait until the current preparation relinquishes ownership."""
        ...


class Host(typing.Protocol):
    """Presentation uses these controls and selections independently of app assembly."""

    year_directory: pathlib.Path
    report_path: pathlib.Path
    branches: peri_scribe.phases.Branches
    visible_state: peri_scribe.monitor.model.State
    selected_run: str
    selected_phase: peri_scribe.phases.Path
    following: bool
    rendered_report: peri_scribe.monitor.storage.Report
    rows: dict[textual.widgets.DataTable, dict[str, peri_scribe.monitor.events.Event]]
    tree_nodes: dict[
        peri_scribe.phases.Path,
        textual.widgets.tree.TreeNode[peri_scribe.monitor.model.PhaseState],
    ]

    @property
    def controller(self) -> Preparation:
        """The presentation owner, independent of its implementation."""
        ...

    @property
    def is_running(self) -> bool:
        """Whether the terminal event loop remains active."""
        ...

    @typing.overload
    def query_one(self, selector: str) -> textual.widget.Widget: ...

    @typing.overload
    def query_one[Widget: textual.widget.Widget](
        self,
        selector: type[Widget],
    ) -> Widget: ...

    @typing.overload
    def query_one[Widget: textual.widget.Widget](
        self,
        selector: str,
        expect_type: type[Widget],
    ) -> Widget: ...

    def query_one[Widget: textual.widget.Widget](
        self,
        selector: str | type[Widget],
        expect_type: type[Widget] | None = None,
    ) -> Widget | textual.widget.Widget:
        """Resolve the actual mounted control with its framework-provided type.

        Args:
            selector: The control's selector or widget class.
            expect_type: The required widget class for a string selector.

        Returns:
            The matching mounted control.
        """
        ...

    def query(
        self,
        selector: str,
    ) -> textual.css.query.DOMQuery[textual.widget.Widget]:
        """Check attachment using the terminal's own control collection.

        Args:
            selector: The controls whose presence matters to publication.

        Returns:
            The framework's matching control collection.
        """
        ...

    def call_after_refresh(self, callback: collections.abc.Callable[[], None]) -> bool:
        """Let actual frame completion authorize subsequent preparation.

        Args:
            callback: The action eligible after the next completed frame.

        Returns:
            Whether the terminal accepted the callback.
        """
        ...

    def notify(
        self,
        message: str,
        *,
        severity: typing.Literal["information", "warning", "error"] = "information",
    ) -> None:
        """Present a collection failure without coupling its reader to the terminal.

        Args:
            message: The user-facing collection result.
            severity: The importance of the notification.
        """
        ...

    def current_run(self) -> peri_scribe.monitor.model.Run:
        """Return the command selected in the retained inspection snapshot."""
        ...

    def action_view(self, name: str) -> None:
        """Select the destination for explicitly requested evidence.

        Args:
            name: The terminal content destination.
        """
        ...
