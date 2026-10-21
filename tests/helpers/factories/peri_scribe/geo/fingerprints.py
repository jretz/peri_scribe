"""Mutate independent JSON copies at arbitrary generated tree positions."""

from __future__ import annotations

import copy
import typing


type Path = tuple[str | int, ...]


def paths(value: object) -> list[Path]:
    """Include every container and scalar location, including the complete root.

    Args:
        value: An acyclic native JSON tree.

    Returns:
        All possible replacement paths in deterministic traversal order.
    """
    result: list[Path] = [()]
    children = (
        value.items()
        if isinstance(value, dict)
        else enumerate(value)
        if isinstance(value, list)
        else ()
    )
    for key, child in children:
        result.extend((key, *path) for path in paths(child))
    return result


def changed_copy(value: object, replacement: object, position: int) -> object:
    """Change one independently owned root, container, or scalar without editing input.

    Args:
        value: The original native JSON tree.
        replacement: A separately copied replacement tree.
        position: Deterministically selects a valid path modulo the number of locations.

    Returns:
        A detached value containing the selected replacement.
    """
    result = copy.deepcopy(value)
    locations = paths(result)
    path = locations[position % len(locations)]
    if not path:
        return copy.deepcopy(replacement)
    parent = result
    for part in path[:-1]:
        parent = (
            typing.cast("list[object]", parent)[part]
            if isinstance(part, int)
            else typing.cast("dict[str, object]", parent)[part]
        )
    final = path[-1]
    if isinstance(final, int):
        typing.cast("list[object]", parent)[final] = copy.deepcopy(replacement)
    else:
        typing.cast("dict[str, object]", parent)[final] = copy.deepcopy(replacement)
    return result
