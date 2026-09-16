"""Generate classification examples with constrained domains."""

from __future__ import annotations

import datetime

import hypothesis.strategies
import shapely.affinity

import peri_scribe.perimeters.classification_data
import tests.helpers.factories.peri_scribe.perimeters.signals
import tests.helpers.strategies.geometry


@hypothesis.strategies.composite
def observation_sequences(
    draw: hypothesis.strategies.DrawFn,
) -> list[peri_scribe.perimeters.classification_data.FireObservation]:
    """Mix repeated mappings and source coordinate systems around a state boundary.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        Observations with overlapping polygons, holes, points, and missing geometry.
    """
    geometry = hypothesis.strategies.one_of(
        hypothesis.strategies.none(),
        hypothesis.strategies.just(shapely.Polygon()),
        tests.helpers.strategies.geometry.local_shapes().map(
            lambda shape: shapely.affinity.translate(
                shapely.affinity.scale(shape, xfact=0.5, yfact=0.5, origin=(0, 0)),
                xoff=-121,
                yoff=35,
            ),
        ),
    )
    catalog = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.tuples(
                hypothesis.strategies.from_type(
                    peri_scribe.perimeters.classification_data.FireSourceKind,
                ),
                geometry,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    mappings = draw(
        hypothesis.strategies.lists(
            hypothesis.strategies.sampled_from(catalog),
            max_size=12,
        ),
    )
    return [
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            source,
            shape,
            serial_number=index,
        )
        for index, (source, shape) in enumerate(mappings)
    ]


@hypothesis.strategies.composite
def extent_histories(
    draw: hypothesis.strategies.DrawFn,
) -> tuple[
    list[peri_scribe.perimeters.classification_data.FireObservation],
    list[peri_scribe.perimeters.classification_data.FireObservation],
]:
    """Keep the latest usable perimeters explicit while varying irrelevant observations.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        The latest perimeter pair and a permuted history with older and unusable rows.
    """
    base = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
    sources = (
        tests.helpers.factories.peri_scribe.perimeters.signals.FIRIS,
        tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_PERIMETER,
    )
    latest = [
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            source,
            draw(tests.helpers.strategies.geometry.rectangles()),
            observed_at=base
            + datetime.timedelta(
                hours=draw(hypothesis.strategies.integers(-24, 24)),
            ),
        )
        for source in sources
    ]
    history = list(latest)
    history.extend(
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            draw(hypothesis.strategies.sampled_from(sources)),
            draw(tests.helpers.strategies.geometry.rectangles()),
            observed_at=base
            - datetime.timedelta(
                hours=draw(hypothesis.strategies.integers(25, 100)),
            ),
            serial_number=serial + 1,
        )
        for serial in range(draw(hypothesis.strategies.integers(0, 8)))
    )
    history.extend(
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            source,
            shapely.Polygon(),
            observed_at=base + datetime.timedelta(days=2),
        )
        for source in sources
    )
    history.append(
        tests.helpers.factories.peri_scribe.perimeters.signals.observation(
            tests.helpers.factories.peri_scribe.perimeters.signals.WFIGS_LOCATION,
            draw(tests.helpers.strategies.geometry.rectangles()),
            observed_at=base + datetime.timedelta(days=2),
        ),
    )
    return latest, list(draw(hypothesis.strategies.permutations(history)))
