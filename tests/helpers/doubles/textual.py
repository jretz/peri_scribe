"""Control delivery of a real terminal resize without changing layout behavior."""

import asyncio
import collections.abc
import dataclasses
import typing

import textual.app
import textual.events
import textual.geometry
import textual.message
import textual.widgets


class ResizeApp(textual.app.App[None]):
    """A filling child exposes whether the compositor used the terminal's new size."""

    CSS = "#body { width: 1fr; height: 1fr; }"

    @typing.override
    def compose(self) -> textual.app.ComposeResult:
        """Yield one child whose region tracks actual screen layout.

        Yields:
            A visible widget filling the available terminal space.
        """
        yield textual.widgets.Static("Layout", id="body")


@dataclasses.dataclass(frozen=True, kw_only=True)
class ResizeGate:
    """Keep screen delivery separate from completion of the real Pilot operation."""

    target: textual.geometry.Size
    post_message: collections.abc.Callable[[textual.message.Message], bool]
    resize_terminal: collections.abc.Callable[
        [int, int],
        collections.abc.Awaitable[None],
    ]
    messages: list[textual.events.Resize] = dataclasses.field(default_factory=list)
    requested: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    returned: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    released: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    def capture(self, message: textual.message.Message) -> bool:
        """Hold the requested screen resize before it enters the screen's queue.

        Args:
            message: The real message sent to the mounted screen.

        Returns:
            Whether the message was held or accepted by the actual screen queue.
        """
        if (
            not self.released.is_set()
            and isinstance(message, textual.events.Resize)
            and message.size == self.target
        ):
            self.messages.append(message)
            self.requested.set()
            return True
        return self.post_message(message)

    async def observe(self, width: int, height: int) -> None:
        """Expose the real Pilot return while screen delivery remains controlled.

        Args:
            width: Requested terminal width in cells.
            height: Requested terminal height in cells.
        """
        await self.resize_terminal(width, height)
        await self.requested.wait()
        self.returned.set()

    def release(self) -> None:
        """Allow screen layout and unblock observation during failure cleanup."""
        self.released.set()
        self.requested.set()
        for message in self.messages:
            self.post_message(message)
