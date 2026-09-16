"""Provide data builders and stand-ins for border classification tests."""

from __future__ import annotations

import datetime
import typing

import geopandas
import hypothesis.strategies
import shapely.affinity
import shapely.geometry

import peri_scribe.models
import peri_scribe.perimeters.classification_data
import tests.geometry_strategies
import tests.peri_scribe.perimeters.border_helpers
from peri_scribe.units import units


CALIFORNIA_BOX_WGS84 = shapely.geometry.box(-126.0, 31.0, -119.0, 40.0)


CA_BORDER_WGS84 = shapely.geometry.LineString([(-119.0, 38.0), (-119.0, 40.0)])


def overlapping_observation_cases() -> list[
    tuple[list[shapely.Geometry], tuple[int, ...]]
]:
    """Keep fixed overlap cases independent of Hypothesis's example database.

    Returns:
        Source polygons and the order in which their observations repeat.
    """
    cases: list[tuple[list[shapely.Geometry], tuple[int, ...]]] = [
        (
            [
                shapely.Polygon([(-121, bottom), (-120, bottom), (-121, bottom + 1)]),
                shapely.Polygon(
                    shapely.box(-121, bottom, -119.5, bottom + 1.5).exterior,
                    [shapely.box(-120.5, bottom + 0.5, -120, bottom + 1).exterior],
                ),
            ],
            order,
        )
        for bottom, order in [(35, (0, 1)), (36, (1, 0, 0))]
    ]
    cases.append((
        [
            shapely.Polygon(
                shapely.box(left, 37, left + 1.5, 38.5).exterior,
                [shapely.box(left + 0.5, 37.5, left + 1, 38).exterior],
            )
            for left in (-120.5, -120)
        ],
        (0, 0, 1),
    ))
    return cases


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
        tests.geometry_strategies.local_shapes().map(
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
        tests.peri_scribe.perimeters.border_helpers.observation(
            source,
            shape,
            serial_number=index,
        )
        for index, (source, shape) in enumerate(mappings)
    ]


def full_projected_union(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
) -> shapely.Geometry | None:
    """Provide a union reference without deduplication or one-sided shortcuts.

    Args:
        observations: Source observations before projection.

    Returns:
        Their complete union in California Albers, or None without usable geometry.
    """
    by_reference: dict[int, list[shapely.Geometry]] = {}
    for observation in observations:
        if observation.geometry is not None and not observation.geometry.is_empty:
            reference = (
                peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                    observation.source
                ]
            )
            by_reference.setdefault(reference, []).append(observation.geometry)
    projected = [
        geometry
        for reference, geometries in by_reference.items()
        for geometry in geopandas.GeoSeries(geometries, crs=reference).to_crs(
            peri_scribe.models.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID,
        )
    ]
    return shapely.union_all(projected) if projected else None


def assert_same_projected_coverage(
    actual: shapely.Geometry,
    expected: shapely.Geometry,
) -> None:
    """Compare coverage despite overlapping parts and overlay rounding differences.

    Args:
        actual: A projected union or an unmerged collection of observation geometries.
        expected: The complete reference union in the same meter-based projection.
    """
    merged = shapely.union_all([actual])
    # Overlay rounding can leave thin interior holes, so allow one micrometer of
    # coverage difference.
    tolerance = 1e-6 * units.meters
    assert expected.buffer(tolerance.m_as("meter")).covers(merged)
    assert merged.buffer(tolerance.m_as("meter")).covers(expected)
    assert merged.symmetric_difference(expected).area * units.meters**2 <= (
        (merged.length + expected.length) * units.meters * tolerance
    )


def projected_boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """Place the synthetic state boundary in the classification's working projection.

    Returns:
        The synthetic California box and border in California Albers.
    """
    projected = geopandas.GeoSeries(
        [CALIFORNIA_BOX_WGS84, CA_BORDER_WGS84],
        crs=peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID,
    ).to_crs(peri_scribe.models.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID)
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=projected.iloc[0],
        border=projected.iloc[1],
    )


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
        tests.peri_scribe.perimeters.border_helpers.FIRIS,
        tests.peri_scribe.perimeters.border_helpers.WFIGS_PERIMETER,
    )
    latest = [
        tests.peri_scribe.perimeters.border_helpers.observation(
            source,
            draw(tests.geometry_strategies.rectangles()),
            observed_at=base
            + datetime.timedelta(
                hours=draw(hypothesis.strategies.integers(-24, 24)),
            ),
        )
        for source in sources
    ]
    history = list(latest)
    history.extend(
        tests.peri_scribe.perimeters.border_helpers.observation(
            draw(hypothesis.strategies.sampled_from(sources)),
            draw(tests.geometry_strategies.rectangles()),
            observed_at=base
            - datetime.timedelta(
                hours=draw(hypothesis.strategies.integers(25, 100)),
            ),
            serial_number=serial + 1,
        )
        for serial in range(draw(hypothesis.strategies.integers(0, 8)))
    )
    history.extend(
        tests.peri_scribe.perimeters.border_helpers.observation(
            source,
            shapely.Polygon(),
            observed_at=base + datetime.timedelta(days=2),
        )
        for source in sources
    )
    history.append(
        tests.peri_scribe.perimeters.border_helpers.observation(
            tests.peri_scribe.perimeters.border_helpers.WFIGS_LOCATION,
            draw(tests.geometry_strategies.rectangles()),
            observed_at=base + datetime.timedelta(days=2),
        ),
    )
    return latest, list(draw(hypothesis.strategies.permutations(history)))


def classifiable_record(
    *,
    geometry: shapely.geometry.base.BaseGeometry,
    observed_at: datetime.datetime | None = None,
    identifiers: frozenset[str] = frozenset(),
    mission: str | None = None,
    point_of_origin_state: str | None = None,
    point_of_origin_fips: str | None = None,
) -> peri_scribe.models.FireRecord:
    """Build a fire record for classification tests.

    Args:
        geometry: Geometry supplied for the selected spatial case.
        observed_at: Observation time attached to the mapping, or None if unknown.
        identifiers: Fire identifiers supplied for identity matching.
        mission: Mapping mission identifier, or None when unavailable.
        point_of_origin_state: Reported origin state, or None when unavailable.
        point_of_origin_fips: Reported origin FIPS code, or None when unavailable.

    Returns:
        The fire record, named "Fire" and active.
    """
    return peri_scribe.models.FireRecord(
        name="Fire",
        status=peri_scribe.models.FireStatus.ACTIVE,
        identifiers=identifiers,
        geometry=geometry,
        observed_at=observed_at,
        mission=mission,
        point_of_origin_state=point_of_origin_state,
        point_of_origin_fips=point_of_origin_fips,
    )


def make_union_recorder(
    *,
    union_inputs: list[list[shapely.Geometry]],
    original_union_all: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Create a callback with controlled dependencies.

    Capture union inputs to verify observation deduplication.

    Args:
        union_inputs: Shared list recording the geometries supplied to each union.
        original_union_all: Original union operation used to preserve geometric results.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_union_all(geometries: list[shapely.Geometry]) -> shapely.Geometry:
        """Capture union inputs to verify observation deduplication.

        Args:
            geometries: Geometries supplied to the union operation.

        Returns:
            The union of the supplied geometries.
        """
        union_inputs.append(list(geometries))
        return original_union_all(geometries)

    return recording_union_all


def make_reproject_recorder(
    *,
    reprojected: list[tuple[int, bytes]],
    original: typing.Callable[..., shapely.Geometry],
) -> typing.Callable[..., shapely.Geometry]:
    """Create a callback with controlled dependencies.

    Capture reprojection inputs to verify source-specific geometry handling.

    Args:
        reprojected: Shared list recording destination references and input geometry
            bytes.
        original: Original operation whose results the callback preserves.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def recording_reproject(geometry: shapely.Geometry, wkid: int) -> shapely.Geometry:
        """Capture reprojection inputs to verify source-specific geometry handling.

        Args:
            geometry: Geometry supplied for the selected spatial case.
            wkid: Identifier of the requested destination coordinate system.

        Returns:
            The geometry projected into the requested coordinate system.
        """
        reprojected.append((wkid, geometry.wkb))
        return original(geometry, wkid)

    return recording_reproject
