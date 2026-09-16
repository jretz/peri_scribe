"""Generate grouping examples with constrained domains."""

from __future__ import annotations

import hypothesis.strategies
import shapely

import peri_scribe.models


@hypothesis.strategies.composite
def local_geometries(draw: hypothesis.strategies.DrawFn) -> shapely.Geometry:
    """Include touching, nearby, distant, and duplicate point and polygon locations.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A nonempty geometry on a small coordinate grid in degrees.
    """
    longitude = draw(hypothesis.strategies.integers(0, 8)) / 32
    latitude = draw(hypothesis.strategies.integers(0, 8)) / 32
    longitude += 2 * draw(hypothesis.strategies.integers(0, 2))
    if draw(hypothesis.strategies.booleans()):
        return shapely.Point(longitude, latitude)
    return shapely.box(longitude, latitude, longitude + 1 / 32, latitude + 1 / 32)


def fire_records() -> hypothesis.strategies.SearchStrategy[
    list[peri_scribe.models.FireRecord]
]:
    """Allow identifier aliases and spatial name matches to form transitive groups.

    Returns:
        Short record lists with overlapping identifiers, names, and locations.
    """
    return hypothesis.strategies.lists(
        hypothesis.strategies.builds(
            peri_scribe.models.FireRecord,
            name=hypothesis.strategies.just("River"),
            status=hypothesis.strategies.from_type(peri_scribe.models.FireStatus),
            identifiers=hypothesis.strategies.frozensets(
                hypothesis.strategies.sampled_from(("id-a", "id-b", "id-c")),
                max_size=2,
            ),
            names=hypothesis.strategies.frozensets(
                hypothesis.strategies.sampled_from(("river", "canyon", "ridge")),
                min_size=1,
                max_size=2,
            ),
            geometry=hypothesis.strategies.one_of(
                hypothesis.strategies.none(),
                hypothesis.strategies.just(shapely.Point()),
                local_geometries(),
            ),
        ),
        max_size=15,
    )
