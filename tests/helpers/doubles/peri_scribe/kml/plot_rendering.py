"""Replace plot rendering dependencies with controlled test doubles."""

from __future__ import annotations

import typing


def make_pre_render_recorder(*, calls: list[str]) -> typing.Callable[..., None]:
    """Create a callback to record when the pre-render callback runs.

    Args:
        calls: Shared list recording dependency calls for assertions.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def record() -> None:
        """Record when the pre-render callback runs."""
        calls.append("before")

    return record
