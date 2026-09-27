"""Seeded finite-case generation preserves deterministic formal-suite coverage."""

from __future__ import annotations

import collections.abc
import typing


if typing.TYPE_CHECKING:
    import numpy as np


def choose[Value](
    generator: np.random.Generator,
    values: collections.abc.Sequence[Value],
) -> Value:
    """Select domain objects without coercing geometry or Boolean values through arrays.

    Args:
        generator: Reproducible finite-case generator.
        values: Explicit domain values eligible for this case.

    Returns:
        One supplied value with its original Python type.
    """
    return values[int(generator.integers(len(values)))]
