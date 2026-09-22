"""Generate reuse examples with constrained domains."""

import hypothesis.strategies
import shapely

import spatial_data.layers
import tests.helpers.factories.geography


@hypothesis.strategies.composite
def history_layers(
    draw: hypothesis.strategies.DrawFn,
) -> list[spatial_data.layers.LayerData]:
    """Interleave cached fires across layers with missing geometry and empty histories.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Small history layers with repeated fire keys and distinct row contents.
    """
    coordinates = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.tuples(
            hypothesis.strategies.integers(-179, 179),
            hypothesis.strategies.integers(-80, 80),
        ),
    )
    layers = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.sampled_from(["perimeters", "points", "incidents"]),
            hypothesis.strategies.lists(
                hypothesis.strategies.tuples(
                    hypothesis.strategies.sampled_from(["first", "second", "third"]),
                    hypothesis.strategies.integers(0, 1000),
                    coordinates,
                ),
                max_size=8,
            ),
            min_size=1,
            max_size=3,
        ),
    )
    return [
        spatial_data.layers.LayerData(
            name=name,
            dataframe=tests.helpers.factories.geography.geo_frame(
                {
                    "derivation_key": [key for key, _revision, _point in rows],
                    "revision": [revision for _key, revision, _point in rows],
                },
                [
                    None if point is None else shapely.Point(point)
                    for _key, _revision, point in rows
                ],
            ),
        )
        for name, rows in layers.items()
    ]
