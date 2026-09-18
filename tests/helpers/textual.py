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
    """Keep terminal actions and rendering on the mounted application's event loop."""

    app: Application
    pilot: textual.pilot.Pilot[None]

    async def refresh(self) -> None:
        """Wait for queued widget changes to reach the composed screen."""
        await self.pilot.pause(0)
        await self.app.wait_for_refresh()

    async def drag(
        self,
        divider: textual.widget.Widget,
        movement: tuple[int, int],
    ) -> None:
        """Exercise pointer capture outside the divider's original bounds.

        Args:
            divider: The visible divider to move.
            movement: Horizontal and vertical pointer movement in terminal cells.
        """
        position = divider.region.offset
        destination = (position.x + movement[0], position.y + movement[1])
        await self.pilot.mouse_down(divider)
        await self.pilot.hover(offset=destination)
        await self.pilot.mouse_up(offset=destination)


async def invoke[Result](
    callback: collections.abc.Callable[..., Result],
    *args: object,
) -> Result:
    """Let queued terminal messages run after a synchronous widget action.

    Args:
        callback: The user action or widget mutation.
        args: Positional arguments for that action.

    Returns:
        The action's result after dispatch within the terminal event loop.
    """
    result = callback(*args)
    await asyncio.sleep(0)
    return result


async def scroll_end(widget: textual.widget.Widget) -> None:
    """Capture the final layout and paint before inspecting scrolled content.

    Args:
        widget: The mounted container whose last content must be visible.
    """
    await widget.wait_for_refresh()
    completed = asyncio.Event()
    widget.scroll_end(animate=False, on_complete=completed.set)
    await completed.wait()
    await widget.wait_for_refresh()


@contextlib.asynccontextmanager
async def mounted[Application: textual.app.App[None]](
    app: Application,
) -> typing.AsyncIterator[Session[Application]]:
    """Give each test fresh widgets and close their tasks before leaving the loop.

    Args:
        app: The isolated terminal application to exercise.

    Yields:
        The mounted app and its pilot on the current test's event loop.
    """
    async with app.run_test(size=(120, 42)) as pilot:
        yield Session(app=app, pilot=pilot)
