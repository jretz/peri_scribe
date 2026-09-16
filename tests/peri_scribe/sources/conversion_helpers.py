"""Generate GeoJSON features with sparse attributes and mixed geometry."""

from __future__ import annotations

import typing

import hypothesis.strategies
import pandas as pd
import shapely

import tests.geometry_strategies


if typing.TYPE_CHECKING:
    import geopandas


def comparable_attributes(frame: geopandas.GeoDataFrame) -> pd.DataFrame:
    """Treat Pandas null representations and chunk-dependent dtypes as equivalent.

    Args:
        frame: Features read together or in separate chunks.

    Returns:
        Attribute values with uniform missing-value representation.
    """
    attributes = pd.DataFrame(frame.drop(columns=frame.geometry.name), dtype=object)
    return attributes.where(attributes.notna(), None)


@hypothesis.strategies.composite
def feature_collections(draw: hypothesis.strategies.DrawFn) -> list[dict[str, object]]:
    """Exercise Unicode attributes, missing properties, and nullable geometry in chunks.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        JSON-serializable GeoJSON features with varied property presence.
    """
    footprint = draw(tests.geometry_strategies.footprints())
    attributes = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.dictionaries(
                hypothesis.strategies.sampled_from(("name", "count", "category")),
                hypothesis.strategies.one_of(
                    hypothesis.strategies.none(),
                    hypothesis.strategies.integers(-1_000_000, 1_000_000),
                    hypothesis.strategies.text(max_size=30),
                ),
            ),
            max_size=20,
        ),
    )
    return [
        {
            "type": "Feature",
            "properties": properties,
            "geometry": draw(
                hypothesis.strategies.sampled_from((
                    None,
                    shapely.geometry.mapping(shapely.Point(0, 0)),
                    shapely.geometry.mapping(footprint),
                )),
            ),
        }
        for properties in attributes
    ]
