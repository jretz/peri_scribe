"""Observe status navigation requests without mounting the destination pipeline."""

import typing

import textual
import textual.app

import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets


class StatusApp(textual.app.App[None]):
    """A real status pane emits evidence requests to a recording parent."""

    def __init__(self) -> None:
        """Give each test its own navigation history."""
        super().__init__()
        self.opened: list[peri_scribe.monitor.status.Target] = []

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Exercise status presentation without unrelated terminal controls.

        Yields:
            The complete status pane.
        """
        yield peri_scribe.monitor.status_widgets.StatusPane()

    @textual.on(peri_scribe.monitor.status_widgets.OpenEvidence)
    def record_evidence(
        self,
        message: peri_scribe.monitor.status_widgets.OpenEvidence,
    ) -> None:
        """Retain requested targets for assertions about navigation behavior.

        Args:
            message: The evidence selected through a status control.
        """
        self.opened.append(message.target)
