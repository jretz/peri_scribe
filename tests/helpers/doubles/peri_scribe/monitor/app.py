"""Reproduce presentation teardown while a report refresh is suspended."""

from __future__ import annotations

import typing


if typing.TYPE_CHECKING:
    import textual.widgets


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
