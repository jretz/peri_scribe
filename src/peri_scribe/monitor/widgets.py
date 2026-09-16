"""Terminal widgets translate user gestures into monitor actions."""

import typing

import textual.app
import textual.containers
import textual.events
import textual.message
import textual.widgets


class EventTable(textual.widgets.DataTable):
    """Browsing older rows pauses following before a redraw can move the cursor."""

    class Browse(textual.message.Message):
        """The reader has chosen to inspect older records."""

    def on_key(self, event: textual.events.Key) -> None:
        """Treat upward navigation as an explicit request to leave the live edge.

        Args:
            event: The user's keyboard input.
        """
        if event.key in {"up", "pageup", "home"}:
            self.post_message(self.Browse())

    def on_mouse_scroll_up(self, _event: textual.events.MouseScrollUp) -> None:
        """Keep wheel scrolling stable as new records arrive.

        Args:
            _event: The wheel gesture, whose position does not affect following.
        """
        self.post_message(self.Browse())


class Stream(textual.containers.Vertical):
    """Pipeline and full-width log views share the same controls and event table."""

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Keep both presentations consistent as filtering and inspection evolve.

        Yields:
            The stream's filter controls and selectable event rows.
        """
        with textual.containers.Horizontal(classes="filters"):
            yield textual.widgets.Input(
                placeholder="Search events, fire, feed, fields…",
                classes="search",
            )
            yield textual.widgets.Select(
                [
                    (level.upper(), level)
                    for level in ("debug", "info", "warning", "error", "critical")
                ],
                value="info",
                allow_blank=False,
                classes="severity",
            )
        yield EventTable(cursor_type="row", classes="events")


class ReportViewer(textual.widgets.MarkdownViewer):
    """Keep report anchors local while external links open in the browser."""

    def on_markdown_link_clicked(
        self,
        event: textual.widgets.Markdown.LinkClicked,
    ) -> None:
        """Route links without replacing the watched report with another document.

        Args:
            event: The link selected in the rendered report.
        """
        event.stop()
        event.prevent_default()
        if event.href.startswith("#"):
            self.document.goto_anchor(event.href[1:])
        else:
            self.app.open_url(event.href)
