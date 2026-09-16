"""Generate interleaved cache insertions with controlled digest collisions."""

from __future__ import annotations

import hypothesis.strategies
import shapely


@hypothesis.strategies.composite
def observations(draw: hypothesis.strategies.DrawFn) -> list[tuple[bytes, bytes]]:
    """Reuse a small catalog to make duplicates and collisions common.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Ordered digest and WKB pairs, including possible repeat observations.
    """
    coordinates = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.integers(-170, 170),
                hypothesis.strategies.integers(-70, 70),
                hypothesis.strategies.integers(0, 100),
            ),
            min_size=1,
            max_size=8,
            unique=True,
        ),
    )
    catalog = [
        (
            draw(hypothesis.strategies.integers(0, 3)).to_bytes(1),
            shapely.to_wkb(
                shapely.set_srid(shapely.Point(*point), 4326),
                include_srid=True,
            ),
        )
        for point in coordinates
    ]
    return draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.sampled_from(catalog),
            min_size=1,
            max_size=25,
        ),
    )
