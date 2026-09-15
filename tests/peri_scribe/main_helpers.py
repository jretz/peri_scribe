"""Provide data builders and stand-ins for main tests."""

from __future__ import annotations

import typing


def make_version_lookup_recorder(
    *,
    looked_up_distributions: list[str],
) -> typing.Callable[..., str]:
    """Create a callback with controlled dependencies.

    Capture the distribution name used to retrieve the CLI version.

    Args:
        looked_up_distributions: Shared list recording distribution names used for
            version lookup.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def record_lookup(name: str) -> str:
        """Capture the distribution name used to retrieve the CLI version.

        Args:
            name: Distribution name requested by the CLI version command.

        Returns:
            The fixed version string supplied by this test.
        """
        looked_up_distributions.append(name)
        return "1.2.3"

    return record_lookup
