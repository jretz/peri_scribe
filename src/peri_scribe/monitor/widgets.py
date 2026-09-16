"""Terminal widgets translate user gestures into monitor actions."""

import enum
import typing

import textual.app
import textual.containers
import textual.events
import textual.message
import textual.widget
import textual.widgets


class Dimension(enum.StrEnum):
    """Pane dimensions identify the direction in which a divider can move."""

    WIDTH = "width"
    HEIGHT = "height"


class PaneDivider(textual.widget.Widget, can_focus=True):
    """A shared divider keeps mouse and keyboard resizing consistent across panes."""

    BLANK = True
    DEFAULT_CSS = """
    PaneDivider {
        width: 1; height: 1fr; background: $border; pointer: ew-resize;
    }
    PaneDivider.height {
        width: 1fr; height: 1; pointer: ns-resize;
    }
    PaneDivider:hover, PaneDivider:focus { background: $accent; }
    """

    def __init__(
        self,
        before: textual.widget.Widget,
        after: textual.widget.Widget,
        *,
        dimension: Dimension,
        identifier: str,
    ) -> None:
        """Connect the two panes whose available space is shared.

        Args:
            before: The pane above or to the left of the divider.
            after: The pane below or to the right of the divider.
            dimension: The pane dimension adjusted by dragging.
            identifier: The divider's unique identifier.
        """
        super().__init__(id=identifier, classes=dimension)
        self.before = before
        self.after = after
        self.dimension = dimension
        self.drag_position = 0
        self.drag_size = 0
        directions = "Left/Right" if dimension == Dimension.WIDTH else "Up/Down"
        self.tooltip = f"Drag to resize panes, or focus and use {directions} arrows"

    def resize_panes(self, size: int) -> None:
        """Retain flexible proportions while preventing either pane from disappearing.

        Args:
            size: The requested width or height of the leading pane in terminal cells.
        """
        total = getattr(self.before.size, self.dimension) + getattr(
            self.after.size,
            self.dimension,
        )
        if total <= 0:
            return
        minimum_before, minimum_after = (
            (24, 24) if self.dimension == Dimension.WIDTH else (8, 3)
        )
        minimum_before = min(minimum_before, total // 2)
        minimum_after = min(minimum_after, total // 2)
        size = max(minimum_before, min(size, total - minimum_after))
        setattr(self.before.styles, self.dimension, f"{size}fr")
        setattr(self.after.styles, self.dimension, f"{total - size}fr")

    def mouse_position(self, event: textual.events.MouseEvent) -> int:
        """Screen coordinates keep dragging stable as the divider itself moves.

        Args:
            event: The current pointer event.

        Returns:
            The pointer coordinate along the resizable dimension.
        """
        return event.screen_x if self.dimension == Dimension.WIDTH else event.screen_y

    def on_mouse_down(self, event: textual.events.MouseDown) -> None:
        """Capture primary-button drags so the pointer can leave the narrow divider.

        Args:
            event: The button press that may begin a resize.
        """
        if event.button == 1:
            self.drag_position = self.mouse_position(event)
            self.drag_size = getattr(self.before.size, self.dimension)
            self.focus()
            self.capture_mouse()
            event.stop()

    def on_mouse_move(self, event: textual.events.MouseEvent) -> None:
        """Continue captured drags over either neighboring pane.

        Args:
            event: The pointer position during a possible drag.
        """
        if self.app.mouse_captured is self:
            self.resize_panes(
                self.drag_size + self.mouse_position(event) - self.drag_position,
            )
            event.stop()

    def on_mouse_up(self, event: textual.events.MouseUp) -> None:
        """Release capture so later pointer movement cannot resize a pane.

        Args:
            event: The end of the drag, possibly outside the divider.
        """
        if event.button == 1 and self.app.mouse_captured is self:
            self.on_mouse_move(event)
            self.release_mouse()
            event.stop()

    def on_key(self, event: textual.events.Key) -> None:
        """Make resizing available in terminals without mouse input.

        Args:
            event: The key pressed while the divider has focus.
        """
        directions = (
            {"left": -1, "right": 1}
            if self.dimension == Dimension.WIDTH
            else {"up": -1, "down": 1}
        )
        if event.key in directions:
            self.resize_panes(
                getattr(self.before.size, self.dimension) + directions[event.key],
            )
            event.stop()
            event.prevent_default()


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
