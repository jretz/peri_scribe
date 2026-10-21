"""Observe real common-fact formatting without replacing its rendered values."""

from __future__ import annotations

import collections.abc
import typing


if typing.TYPE_CHECKING:
    import peri_scribe.presentation.descriptions


def record_rows(
    original: collections.abc.Callable[
        [peri_scribe.presentation.descriptions.FireDescription],
        list[tuple[str, str | None]],
    ],
    calls: list[peri_scribe.presentation.descriptions.FireDescription],
) -> collections.abc.Callable[
    [peri_scribe.presentation.descriptions.FireDescription],
    list[tuple[str, str | None]],
]:
    """Record every actual formatting request before delegating to the formatter.

    Args:
        original: The production row formatter.
        calls: Requests observed in order, owned by one test.

    Returns:
        A recorder that preserves the production formatter's complete result.
    """

    def rows(
        description: peri_scribe.presentation.descriptions.FireDescription,
    ) -> list[tuple[str, str | None]]:
        """Record and format one complete description.

        Args:
            description: Current complete fire facts.

        Returns:
            Every formatted row produced by the original function.
        """
        calls.append(description)
        return original(description)

    return rows
