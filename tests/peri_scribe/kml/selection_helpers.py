"""Construct collisions and known identity partitions for KML selection tests."""

from __future__ import annotations

import typing

import hypothesis.strategies
import pandas as pd

import tests.factories


if typing.TYPE_CHECKING:
    import geopandas


@hypothesis.strategies.composite
def aliased_histories(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[geopandas.GeoDataFrame, dict[str, str], dict[tuple[str, str], list[int]]]:
    """Keep canonical identity independent of each row's spelling and index label.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        History rows, their alias map, and the expected row ids per tagged identity.
    """
    records = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.one_of(
                    hypothesis.strategies.none(),
                    hypothesis.strategies.integers(0, 2),
                ),
                hypothesis.strategies.sampled_from(["0", "1", "2", "River"]),
                hypothesis.strategies.booleans(),
            ),
            max_size=25,
        ),
    )
    identifiers = []
    expected: dict[tuple[str, str], list[int]] = {}
    for row_id, (group, name, alias) in enumerate(records):
        if group is None:
            identifiers.append(
                draw(hypothesis.strategies.sampled_from([None, pd.NA, float("nan")])),
            )
            key = ("name", name)
        else:
            identifiers.append(f"alias-{group}" if alias else str(group))
            key = ("id", str(group))
        expected.setdefault(key, []).append(row_id)
    frame = tests.factories.geo_frame(
        {
            "fire_identifier": identifiers,
            "fire_name": [name for _group, name, _alias in records],
            "row_id": list(range(len(records))),
        },
        [None] * len(records),
    )
    frame.index = pd.Index(
        draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.integers(-3, 3),
                min_size=len(records),
                max_size=len(records),
            ),
        ),
    )
    aliases = {f"alias-{group}": str(group) for group in range(3)}
    return frame, aliases, expected


@hypothesis.strategies.composite
def filename_requests(
    draw: hypothesis.strategies.DrawFn,
) -> list[tuple[str | None, str]]:
    """Make repeated and colliding fire names common across filename allocations.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Identifier and name pairs, including Unicode, punctuation, and numeric suffixes.
    """
    text = hypothesis.strategies.one_of(
        hypothesis.strategies.sampled_from(
            ["fire", "fire-2", "FIRE!", "🔥", "a/b", ""],
        ),
        hypothesis.strategies.text(max_size=30),
    )
    catalog = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.one_of(hypothesis.strategies.none(), text),
                text,
            ),
            min_size=1,
            max_size=6,
        ),
    )
    return draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.sampled_from(catalog),
            max_size=30,
        ),
    )
