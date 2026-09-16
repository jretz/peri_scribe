"""Generate locations examples with constrained domains."""

from __future__ import annotations

import geopandas
import hypothesis.strategies
import shapely

import tests.helpers.strategies.geometry


@hypothesis.strategies.composite
def city_queries(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[
    shapely.Geometry,
    geopandas.GeoDataFrame,
    list[tuple[str, str, shapely.Point]],
]:
    """Exercise candidate pruning with nearby cities, outliers, ties, and unusable rows.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A fire footprint, candidate rows, and the usable cities for exhaustive search.
    """
    geometry = draw(tests.helpers.strategies.geometry.footprints())
    center = geometry.representative_point()
    offsets = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.integers(-8, 8),
                hypothesis.strategies.integers(-8, 8),
            ),
            min_size=1,
            max_size=6,
        ),
    )
    usable = [
        (f"City {index}", "OR", shapely.Point(center.x + x / 4, center.y + y / 4))
        for index, (x, y) in enumerate(offsets)
    ]
    rows: list[tuple[str | None, str | None, shapely.Geometry | None]] = list(usable)
    rows.extend(
        draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.sampled_from([
                    (None, "OR", center),
                    ("No state", None, center),
                    ("No geometry", "OR", None),
                    ("Empty geometry", "OR", shapely.Point()),
                    ("Wrong geometry", "OR", geometry),
                ]),
                max_size=4,
            ),
        ),
    )
    rows = list(draw(hypothesis.strategies.permutations(rows)))
    frame = geopandas.GeoDataFrame(
        {
            "NAME": [name for name, _state, _geometry in rows],
            "STATE_ABBR": [state for _name, state, _geometry in rows],
        },
        geometry=[point for _name, _state, point in rows],
        crs="EPSG:4326",
        index=draw(
            hypothesis.strategies.lists(
                hypothesis.strategies.integers(-3, 3),
                min_size=len(rows),
                max_size=len(rows),
            ),
        ),
    )
    return geometry, frame, usable
