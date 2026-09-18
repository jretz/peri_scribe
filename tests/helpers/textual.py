"""Keep isolated terminal tests inside one event loop until their app shuts down."""

import asyncio
import collections.abc
import contextlib
import dataclasses
import typing

import textual.app
import textual.pilot
import textual.widget


@dataclasses.dataclass(frozen=True, kw_only=True)
class Session[Application: textual.app.App[None]]:
    """Synchronous tests share the event loop that owns their mounted widgets."""

    app: Application
    runner: asyncio.Runner
    pilot: textual.pilot.Pilot[None]

    def call[Result](
        self,
        callback: collections.abc.Callable[..., Result],
        *args: object,
    ) -> Result:
        """Keep synchronous widget actions inside Textual's running event loop.

        Args:
            callback: The user action or widget mutation.
            args: Positional arguments for that action.

        Returns:
            The action's result after dispatch within the terminal event loop.
        """
        return self.runner.run(invoke(callback, *args))

    def refresh(self) -> None:
        """Wait for queued widget changes to reach the composed screen."""
        self.runner.run(refresh(self.pilot))

    def scroll_end(self, widget: textual.widget.Widget) -> None:
        """Capture the final layout and paint before inspecting scrolled content.

        Args:
            widget: The mounted container whose last content must be visible.
        """
        self.runner.run(scroll_end(widget))

    def drag(self, divider: textual.widget.Widget, movement: tuple[int, int]) -> None:
        """Exercise pointer capture outside the divider's original bounds.

        Args:
            divider: The visible divider to move.
            movement: Horizontal and vertical pointer movement in terminal cells.
        """
        position = divider.region.offset
        destination = (position.x + movement[0], position.y + movement[1])
        self.runner.run(self.pilot.mouse_down(divider))
        self.runner.run(self.pilot.hover(offset=destination))
        self.runner.run(self.pilot.mouse_up(offset=destination))


async def invoke[Result](
    callback: collections.abc.Callable[..., Result],
    *args: object,
) -> Result:
    """Allow synchronous UI actions to schedule terminal messages and timers.

    Args:
        callback: The action that requires a running event loop.
        args: Positional arguments for that action.

    Returns:
        The result of the requested action.
    """
    result = callback(*args)
    await asyncio.sleep(0)
    return result


async def refresh(pilot: textual.pilot.Pilot[None]) -> None:
    """Synchronize rendering with message delivery instead of process CPU idleness.

    Args:
        pilot: The mounted application's event-queue barrier.
    """
    await pilot.pause(0)
    await pilot.app.wait_for_refresh()


async def scroll_end(widget: textual.widget.Widget) -> None:
    """Wait for layout, deferred scrolling, and the resulting painted screen.

    Args:
        widget: The mounted container whose last content must be visible.
    """
    await widget.wait_for_refresh()
    completed = asyncio.Event()
    widget.scroll_end(animate=False, on_complete=completed.set)
    await completed.wait()
    await widget.wait_for_refresh()


@contextlib.contextmanager
def mounted[Application: textual.app.App[None]](
    app: Application,
) -> typing.Iterator[Session[Application]]:
    """Give each test fresh widgets and close their tasks before leaving the loop.

    Args:
        app: The isolated terminal application to exercise.

    Yields:
        The mounted app, its pilot, and their synchronous event-loop runner.
    """
    with asyncio.Runner() as runner:
        stack = contextlib.AsyncExitStack()
        pilot = runner.run(stack.enter_async_context(app.run_test(size=(120, 42))))
        try:
            yield Session(app=app, runner=runner, pilot=pilot)
        finally:
            runner.run(stack.aclose())
