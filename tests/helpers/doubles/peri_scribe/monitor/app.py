"""Reproduce presentation teardown while a report refresh is suspended."""

from __future__ import annotations

import asyncio
import collections.abc
import dataclasses
import inspect
import threading
import typing

import peri_scribe.monitor.app
import peri_scribe.monitor.model
import peri_scribe.monitor.storage


if typing.TYPE_CHECKING:
    import pathlib

    import textual.widgets


def hide_report_during_read(
    app: peri_scribe.monitor.app.MonitorApp,
    path: pathlib.Path,
    previous: peri_scribe.monitor.storage.Report,
) -> peri_scribe.monitor.storage.Report:
    """Let a user leave Report before its pending file read completes.

    Args:
        app: The observer receiving a tab change during its worker's read.
        path: The requested report location.
        previous: The snapshot preceding this interrupted refresh.

    Returns:
        New content that must not render while the report is hidden.
    """
    app.call_from_thread(app.action_view, "status")
    return peri_scribe.monitor.storage.Report(content="# Hidden update")


async def remove_viewer_during_update(
    viewer: textual.widgets.MarkdownViewer,
    content: str,
) -> None:
    """Represent shutdown occurring while Markdown rendering yields control.

    Args:
        viewer: The report pane being removed during shutdown.
        content: The pending report text whose rendering is interrupted.
    """
    await viewer.remove()


@dataclasses.dataclass(frozen=True, kw_only=True)
class BlockedArchiveAppend:
    """Hold an archive's state replacement while the live clock delivers new records."""

    started: threading.Event
    release: threading.Event
    append: collections.abc.Callable[..., peri_scribe.monitor.model.State]

    def __call__(
        self,
        state: peri_scribe.monitor.model.State,
        records: tuple[dict[str, object], ...],
        *,
        bounded: bool = True,
    ) -> peri_scribe.monitor.model.State:
        """Expose a stale archive snapshot without delaying independent live ingestion.

        Args:
            state: The snapshot captured before archive processing began.
            records: Archived and current records to replay together.
            bounded: Whether ingestion applies the interactive retention limits.

        Returns:
            The ordinary state projection once the test releases archive processing.

        Raises:
            TimeoutError: The test did not release archive processing.
        """
        if records and records[0].get("run_id") == "archive":
            self.started.set()
            if not self.release.wait(timeout=5):
                message = "Test did not release archive processing"
                raise TimeoutError(message)
        return self.append(state, records, bounded=bounded)


async def tick(callback: collections.abc.Callable[[], object]) -> None:
    """Deliver the registered timer callback independently of the app's message queue.

    Args:
        callback: The observer's actual clock callback, suspended by its fixture.
    """
    result = callback()
    if inspect.isawaitable(result):
        await result
    await asyncio.sleep(0)
