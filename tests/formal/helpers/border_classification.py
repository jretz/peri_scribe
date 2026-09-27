"""Real planar unions and source reprojection distinguish classification contracts."""

import dataclasses
import datetime
import itertools

import pyproj
import shapely

import peri_scribe.models
import peri_scribe.perimeters.classification_data
import spatial_data.geometry
import spatial_data.reference
import tests.formal.helpers.perimeter_evidence
from measurement_units import units


CLASSIFICATIONS = (
    peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA,
    peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER,
    peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER,
    peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER,
    peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA,
)
SIGNALS = (
    peri_scribe.models.BorderSignal.GEOMETRY_OUTSIDE,
    peri_scribe.models.BorderSignal.GEOMETRY_NEAR,
    peri_scribe.models.BorderSignal.EXTENT_DISAGREEMENT,
    peri_scribe.models.BorderSignal.IDENTIFIER_UNIT,
)
BORDER_CELL = 8
SOURCES = (
    peri_scribe.perimeters.classification_data.FireSourceKind.FIRIS_PERIMETER,
    peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_PERIMETER,
)


def classifications() -> list[tuple[bool, ...]]:
    """Contradictory signal combinations also need a deterministic priority.

    Returns:
        All independent geometry, extent, and identifier signal combinations.
    """
    return list(itertools.product((False, True), repeat=5))


def geometry_signal(
    flags: tuple[bool, ...],
) -> peri_scribe.perimeters.classification_data.GeometrySignal:
    """Classification consumes decisions already supplied by geometry analysis.

    Args:
        flags: Crossing, proximity, inside, extent, and identifier decisions.

    Returns:
        Real signal values carrying the supplied three geometry decisions.
    """
    crosses, near, inside, _extent, _identifier = flags
    return peri_scribe.perimeters.classification_data.GeometrySignal(
        distance_to_boundary=0 * units.meters,
        outside_area_fraction=0.0,
        outside_area=0 * units.Unit("meters ** 2"),
        inside_area_fraction=0.0,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def footprint_cases() -> list[tuple[tuple[int, ...], ...]]:
    """Shared cells expose overlap, multiplicity, shortcuts, and border contact.

    Returns:
        Lists of contiguous unit-height rectangles represented by their unit cells.
    """
    parts = tuple(
        tuple(range(start, end))
        for start, end in ((1, 3), (2, 4), (5, 8), (9, 12), (10, 14), (7, 10), (6, 12))
    )
    return [(), *itertools.product(parts, repeat=3)]


def footprint_geometry(cells: tuple[int, ...]) -> shapely.Geometry:
    """A contiguous cell list has exact integer planar area.

    Args:
        cells: Increasing adjacent cell identities.

    Returns:
        Their actual GEOS rectangle.
    """
    return shapely.box(cells[0], 0, cells[-1] + 1, 1)


def boundaries() -> peri_scribe.perimeters.classification_data.Boundaries:
    """A finite synthetic interstate boundary keeps arithmetic independent of map data.

    Returns:
        The inside box and its eastern border in projected coordinates.
    """
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=shapely.box(-10, -10, 8, 10),
        border=shapely.LineString([(8, -10), (8, 10)]),
    )


def planar_config(
    fraction: int,
    absolute: int,
    majority: int,
) -> peri_scribe.perimeters.classification_data.BorderClassificationConfig:
    """Integer percentage thresholds connect the exact policy with real Pint quantities.

    Args:
        fraction: The outside threshold percentage.
        absolute: The outside threshold in square meters.
        majority: The inside threshold percentage.

    Returns:
        Classification thresholds with a two-meter near-border buffer.
    """
    return peri_scribe.perimeters.classification_data.BorderClassificationConfig(
        outside_area_fraction_threshold=fraction / 100,
        outside_area_threshold=absolute * units.Unit("meters ** 2"),
        inside_area_fraction_threshold=majority / 100,
        near_border_buffer=2 * units.meters,
    )


def signal_values(
    signal: peri_scribe.perimeters.classification_data.GeometrySignal,
) -> tuple[float, ...]:
    """No measurement may be hidden when comparing the fast and complete union paths.

    Args:
        signal: Actual classification geometry evidence.

    Returns:
        Every scalar field in stable order.
    """
    return (
        signal.distance_to_boundary.m_as("meters"),
        signal.outside_area_fraction,
        signal.outside_area.m_as("meters ** 2"),
        signal.inside_area_fraction,
        float(signal.crosses),
        float(signal.near),
        float(signal.inside),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Extent:
    """Source recency can disagree with insertion order and snapshot order."""

    source: int
    time: int
    serial: int
    shape: int

    def command(self) -> str:
        """Known exact rectangles avoid substituting another extent decision policy.

        Returns:
            Optional clock, serial, area, and footprint identity.
        """
        area = round(projected_shapes()[self.shape].area)
        return f"{self.time},{self.serial},{area},{self.shape}"

    def production(self) -> peri_scribe.perimeters.classification_data.FireObservation:
        """Feed coordinates traverse the production source-specific PROJ transform.

        Returns:
            A genuine FIRIS or WFIGS observation.
        """
        source = SOURCES[self.source]
        transformer = pyproj.Transformer.from_crs(
            spatial_data.reference.CALIFORNIA_ALBERS_SPATIAL_REFERENCE_ID,
            peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                source
            ],
            always_xy=True,
        )
        return peri_scribe.perimeters.classification_data.FireObservation(
            source=source,
            geometry=spatial_data.geometry.transform_coordinates(
                projected_shapes()[self.shape],
                transformer,
            ),
            observed_at=(
                None
                if self.time < 0
                else tests.formal.helpers.perimeter_evidence.BASE
                + datetime.timedelta(seconds=self.time)
            ),
            serial_number=self.serial,
        )


def projected_shapes() -> tuple[shapely.Geometry, ...]:
    """Near-threshold rectangles have ample margin for projection's numerical error.

    Returns:
        Overlapping, shifted, smaller, and larger ideal projected footprints.
    """
    return tuple(
        shapely.box(start, 0, start + width, 100)
        for start, width in ((0, 100), (0, 104), (0, 106), (10, 104), (0, 90))
    )


def extent_cases() -> list[list[Extent]]:
    """Stale rows, serial ties, absent clocks, and omitted feeds vary independently.

    Returns:
        Complete source observation lists used by the real extent classifier.
    """
    cases: list[list[Extent]] = [[], [Extent(source=0, time=0, serial=0, shape=0)]]
    for time, shape, serial in itertools.product(
        (-1, 0, 1, 86_399, 86_400, 86_401),
        range(5),
        (0, 1),
    ):
        cases.extend([
            [
                Extent(source=0, time=0, serial=0, shape=0),
                Extent(source=1, time=time, serial=serial, shape=shape),
                Extent(source=1, time=0, serial=0, shape=4),
            ],
            [
                Extent(source=0, time=-1, serial=0, shape=0),
                Extent(source=1, time=time, serial=serial, shape=shape),
            ],
        ])
    return cases


def extent_command(values: list[Extent]) -> str:
    """The reference receives shape measurements and clocks before any decision.

    Args:
        values: Observations in their source order.

    Returns:
        The complete executable-reference request.
    """
    matrix = ",".join(
        str(round(first.symmetric_difference(second).area))
        for first in projected_shapes()
        for second in projected_shapes()
    )
    feeds = [
        ";".join(value.command() for value in values if value.source == source)
        or "none"
        for source in (0, 1)
    ]
    return f"extent {feeds[0]} {feeds[1]} {matrix} 86400 105 5"
