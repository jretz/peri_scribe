"""Expose the first cooperative yield while actual tables receive prepared rows."""

import asyncio
import collections.abc
import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class RowNotice:
    """Wake an observer at the next yield without changing table mutation behavior."""

    operation: collections.abc.Callable[..., object]
    added: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    def add_row(self, *args: object, **kwargs: object) -> object:
        """Signal actual row insertion while preserving the underlying result.

        Args:
            args: The prepared cells being inserted.
            kwargs: Row identity and optional table arguments.

        Returns:
            The original table's row key.
        """
        result = self.operation(*args, **kwargs)
        self.added.set()
        return result
