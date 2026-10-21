"""Describe JSON evidence independently as canonical typed immutable trees."""

from __future__ import annotations


def evidence(value: object) -> tuple[object, ...] | None:
    """Retain native scalar encodings and canonical mapping contents declaratively.

    Args:
        value: A finite acyclic tree of native JSON values.

    Returns:
        Its typed evidence tree, or None for an unsupported value or mapping key.
    """
    kind = type(value)
    if isinstance(value, float):
        return kind, value.hex()
    if kind in {str, bool, int, type(None)}:
        return kind, value
    if isinstance(value, dict):
        children = [(key, evidence(child)) for key, child in value.items()]
        supported = all(
            isinstance(key, str) and child is not None for key, child in children
        )
        return (kind, frozenset(children)) if supported else None
    if isinstance(value, list):
        children = tuple(evidence(child) for child in value)
        return None if None in children else (kind, children)
    return None


def same_json_value(left: object, right: object) -> bool:
    """Compare complete declarative evidence without using Python object identity.

    Args:
        left: Current JSON value.
        right: Independently retained comparison value.

    Returns:
        Whether both values have supported identical typed evidence.
    """
    first = evidence(left)
    return first is not None and first == evidence(right)
