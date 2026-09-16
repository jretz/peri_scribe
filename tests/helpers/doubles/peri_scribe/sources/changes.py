"""Replace changes dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing


def make_disappearing_state_unlink(
    *,
    stale_path: pathlib.Path,
    original_unlink: typing.Callable[..., None],
) -> typing.Callable[..., None]:
    """Create a callback to simulate a stale state file disappearing during cleanup.

    Args:
        stale_path: State file that should disappear before cleanup completes.
        original_unlink: Original deletion operation used to remove the selected file.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def flaky_unlink(self: pathlib.Path) -> None:
        """Simulate a stale state file disappearing during cleanup.

        Raises:
            FileNotFoundError: If cleanup targets the stale state file.
        """
        if self == stale_path:
            # The stale file disappears before the cleanup removes it, so the cleanup's
            # unlink reports it missing.
            original_unlink(self)
            raise FileNotFoundError
        original_unlink(self)

    return flaky_unlink
