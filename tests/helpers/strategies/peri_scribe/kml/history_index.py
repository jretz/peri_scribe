"""Generate history index examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies
import pandas as pd


def history_rows() -> hypothesis.strategies.SearchStrategy[list[tuple[object, object]]]:
    """Exercise repeated lookup keys, null conventions, and distinct scalar types.

    Returns:
        Raw identifier and name pairs for a generated history layer.
    """
    values = hypothesis.strategies.sampled_from(
        (None, pd.NA, float("nan"), 0, 1, "0", "1", "", "River", "Cañon"),
    )
    return hypothesis.strategies.lists(
        hypothesis.strategies.tuples(values, values),
        max_size=30,
    )
