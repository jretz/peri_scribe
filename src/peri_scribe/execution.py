"""Share completed work only while one publication owns its inputs."""

from __future__ import annotations

import collections.abc
import contextlib
import contextvars
import enum


class Group(enum.Enum):
    """Release source observations before preparing publication objects."""

    SOURCES = enum.auto()
    DERIVED = enum.auto()
    HISTORIES = enum.auto()
    PRESENTATION = enum.auto()


type Values = dict[Group, dict[collections.abc.Hashable, object]]


CURRENT: contextvars.ContextVar[Values | None] = contextvars.ContextVar(
    "publication_execution",
    default=None,
)


@contextlib.contextmanager
def sharing() -> collections.abc.Iterator[None]:
    """Keep a failed or partial publication from leaking results into another run.

    Yields:
        A fresh execution scope whose references are released when it exits.
    """
    token = CURRENT.set({})
    try:
        yield
    finally:
        CURRENT.reset(token)


def active() -> bool:
    """Report whether the caller owns a bounded publication scope.

    Returns:
        Whether completed work can be retained for the next stage.
    """
    return CURRENT.get() is not None


def get(group: Group, key: collections.abc.Hashable) -> object | None:
    """Return work completed earlier in this execution, if available.

    Args:
        group: The lifetime category containing the result.
        key: The owner's complete input identity within that category.

    Returns:
        The retained result, or None outside a scope or before its first computation.
    """
    values = CURRENT.get()
    return None if values is None else values.get(group, {}).get(key)


def put(group: Group, key: collections.abc.Hashable, value: object) -> None:
    """Keep completed results available without changing standalone function behavior.

    Args:
        group: The result's lifetime category.
        key: The owner's complete input identity within that category.
        value: The completed result and any references needed to validate its identity.
    """
    values = CURRENT.get()
    if values is not None:
        values.setdefault(group, {})[key] = value


def clear(group: Group) -> None:
    """Release objects whose consumers have finished, bounding resident memory.

    Args:
        group: The lifetime category that no later stage needs.
    """
    values = CURRENT.get()
    if values is not None:
        values.pop(group, None)
