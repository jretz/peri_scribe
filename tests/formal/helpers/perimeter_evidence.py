"""Exercise retained version lineage and survey clocks with real source observations."""

import dataclasses
import datetime
import itertools
import math

import numpy as np
import pandas as pd
import shapely

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.perimeters.versions
import spatial_data.measurements
import tests.formal.helpers.generation
import tests.helpers.factories.peri_scribe.perimeters.versions
from measurement_units import units


BASE = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Observation:
    """Source metadata and exact rectangular footprints are independently variable."""

    identity: int
    time: int = 0
    published: int = 0
    serial: int = 0
    object_id: int = 1
    feed: int = 0
    source: int = 2
    category: int = 1
    start: int = 0
    width: int = 1000
    capture: int = -1
    same_year: bool = True
    ancestors: tuple[int, ...] = ()

    def command(self) -> str:
        """Preserve the complete observation without evaluating reconciliation policy.

        Returns:
            A strict Lean observation vector.
        """
        return ",".join(
            map(
                str,
                (
                    self.identity,
                    self.time,
                    self.published,
                    self.serial,
                    self.object_id,
                    self.feed,
                    self.source,
                    self.category,
                    self.start,
                    self.width,
                    self.capture,
                    int(self.same_year),
                    int(self.source == 1),
                    sum(1 << value for value in set(self.ancestors)),
                ),
            ),
        )

    def production(self) -> peri_scribe.perimeters.versions.SourceObservation:
        """Retain genuine GEOS overlap, timestamp parsing, and source-file provenance.

        Returns:
            A production observation whose fields correspond to the formal vector.
        """
        source = None if self.source == 0 else "FIRIS" if self.source == 1 else "Agency"
        attributes: dict[str, object] = {
            "source": source,
            "poly_Source": source,
            "type": None if self.category == 0 else str(self.category),
            "poly_FeatureCategory": None if self.category == 0 else str(self.category),
            "poly_PolygonDateTime": capture_time(
                self.capture,
                same_year=self.same_year,
            ),
        }
        result = tests.helpers.factories.peri_scribe.perimeters.versions.observation(
            source_kind=(
                peri_scribe.perimeters.versions.FIRIS_PERIMETER
                if self.feed == 0
                else peri_scribe.perimeters.versions.WFIGS_PERIMETER
            ),
            geometry=shapely.box(self.start, 0, self.start + self.width, 1),
            observation_time=BASE + datetime.timedelta(seconds=self.time),
            snapshot_time=BASE + datetime.timedelta(seconds=self.published),
            serial_number=self.serial,
            object_id=self.object_id,
            source_file=f"{self.identity}.gpkg",
            attributes=attributes,
        )
        return dataclasses.replace(
            result,
            superseded_sources=tuple(f"{value}.gpkg#1" for value in self.ancestors),
        )


def capture_time(value: int, *, same_year: bool) -> datetime.datetime | None:
    """Year validity is varied independently of elapsed capture time.

    Args:
        value: Seconds after the test epoch, or -1 for missing evidence.
        same_year: Whether the capture belongs to the publication year.

    Returns:
        A parsed-compatible UTC timestamp or missing capture evidence.
    """
    if value < 0:
        return None
    result = BASE + datetime.timedelta(seconds=value)
    return result if same_year else result.replace(year=2025)


def retained(
    observations: list[peri_scribe.perimeters.versions.SourceObservation],
) -> tuple[int, ...]:
    """Compare original source identities, retained effective dates, and all provenance.

    Args:
        observations: The actual retained observations in production order.

    Returns:
        Flat identity, elapsed-time, and lineage-bitset triples.
    """
    result = []
    for observation in observations:
        identity = int(observation.source_file.split(".")[0])
        time = peri_scribe.perimeters.versions.effective_time(observation)
        assert time is not None
        sources = {identity} | {
            int(source.split(".")[0]) for source in observation.superseded_sources
        }
        result.extend((
            identity,
            int((time - BASE).total_seconds()),
            sum(1 << source for source in sources),
        ))
    return tuple(result)


def histories() -> list[list[Observation]]:
    """Exercise anchor boundaries, publication winners, changed objects, and lineage.

    Returns:
        Explicit boundary histories and deterministic independently varied inputs.
    """
    cases: list[list[Observation]] = [[]]
    for delta, start, capture, source in itertools.product(
        (0, 1, 299, 300, 301, 600),
        (0, 4, 5, 6, 25, 26, 1000),
        (-1, 0, 1, 300, 301),
        (0, 1, 2),
    ):
        cases.append([
            Observation(identity=0, published=2, ancestors=(20,)),
            Observation(
                identity=1,
                time=delta,
                published=1,
                start=start,
                capture=capture,
                source=source,
                object_id=2,
                ancestors=(21,),
            ),
            Observation(identity=2, time=delta + 299, published=3, start=start),
        ])
    generator = np.random.default_rng(20260927)
    choose = tests.formal.helpers.generation.choose
    for _ in range(350):
        values = [
            Observation(
                identity=index,
                time=int(generator.integers(1000)),
                published=int(generator.integers(4)),
                serial=int(generator.integers(4)),
                object_id=int(generator.integers(1, 4)),
                feed=int(generator.integers(2)),
                source=int(generator.integers(3)),
                category=int(generator.integers(3)),
                start=choose(generator, (0, 4, 5, 6, 25, 26, 1000)),
                capture=choose(generator, (-1, 0, 299, 300, 900, 1001)),
                same_year=choose(generator, (False, True)),
                ancestors=(20 + index,),
            )
            for index in range(int(generator.integers(1, 7)))
        ]
        cases.append(
            sorted(values, key=lambda item: (item.time, item.serial, item.object_id)),
        )
    return cases


def supersession_cases() -> list[tuple[Observation, list[Observation]]]:
    """Cover contemporaneous and delayed-copy windows independently of geometry.

    Returns:
        Losing observations and preferred choices in descending production order.
    """
    cases = []
    for published, captured, start, same_year in itertools.product(
        (14_399, 14_400, 14_401, 86_400, 172_800, 172_801, 200_000),
        (-1, 0, 1, 14_400, 14_401, 86_400, 200_001),
        (0, 25, 26, 1000),
        (False, True),
    ):
        cases.append((
            Observation(
                identity=0,
                time=published,
                capture=captured,
                same_year=same_year,
                start=start,
                feed=1,
                ancestors=(20,),
            ),
            [
                Observation(identity=1, time=1, ancestors=(21,)),
                Observation(identity=2, time=0, capture=0, ancestors=(22,)),
            ],
        ))
    return cases


@dataclasses.dataclass(frozen=True, kw_only=True)
class Survey:
    """Repeated geometry and capture metadata vary across a complete survey history."""

    time: int
    area: int
    shape: int
    capture: int = -1
    same_year: bool = True
    flight: bool = False

    def command(self) -> str:
        """Expose raw evidence without calculating whether it establishes a survey.

        Returns:
            A Lean survey input vector.
        """
        return ",".join(
            map(
                str,
                (
                    self.time,
                    self.area,
                    self.shape,
                    self.capture,
                    int(self.same_year),
                    int(self.flight),
                ),
            ),
        )


def survey_geometries() -> tuple[shapely.Geometry, ...]:
    """Use small, real WGS84 footprints around both insignificant and substantial edits.

    Returns:
        Geographic footprints with distinct symmetric-difference measurements.
    """
    return tuple(
        shapely.box(-120 + shift, 35, -119.99 + shift, 35.01)
        for shift in (0, 0.000001, 0.00001, 0.0001, 0.001, 0.01)
    )


def survey_matrix(geometries: tuple[shapely.Geometry, ...]) -> str:
    """Integer thresholds permit exact floor conversion of measured acreage differences.

    Args:
        geometries: The concrete geometries used in the production history.

    Returns:
        Measured differences in integral acres; all stored-area thresholds are integral.
    """
    return ",".join(
        str(
            math.floor(
                spatial_data.measurements.area(first.symmetric_difference(second)).m_as(
                    "acres",
                ),
            ),
        )
        for first in geometries
        for second in geometries
    )


def survey_histories() -> list[list[Survey]]:
    """Late capture fields are assessed against the last actual survey, including gaps.

    Returns:
        Fresh, missing, future, and wrong-year evidence across complete histories.
    """
    cases: list[list[Survey]] = [[]]
    for shape, capture, same_year, flight, area in itertools.product(
        range(6),
        (-1, 0, 1, 2, 3),
        (False, True),
        (False, True),
        (100, 200, 1000),
    ):
        cases.append([
            Survey(time=0, area=area, shape=0),
            Survey(time=1, area=area, shape=1),
            Survey(
                time=2,
                area=area,
                shape=shape,
                capture=capture,
                same_year=same_year,
                flight=flight,
            ),
            Survey(time=3, area=area, shape=0, capture=1),
        ])
    return cases


def survey_result(
    values: list[Survey],
    geometries: tuple[shapely.Geometry, ...],
) -> tuple[int, ...]:
    """Keep production survey classification, geometry measurement, and fold intact.

    Args:
        values: Raw survey observations supplied to the formal oracle.
        geometries: Geographic footprints supplying the measured oracle differences.

    Returns:
        The production survey decisions in chronological order.
    """
    frame = pd.DataFrame([
        {
            "observation_time": BASE + datetime.timedelta(seconds=value.time),
            "geometry": geometries[value.shape],
            peri_scribe.geo.measurements.AREA_COLUMN: (value.area * units.acres).m_as(
                "meters ** 2",
            ),
            "source_subsource": "FIRIS" if value.flight else "Agency",
            "source_attributes": {
                "poly_PolygonDateTime": capture_time(
                    value.capture,
                    same_year=value.same_year,
                ),
            },
        }
        for value in reversed(values)
    ])
    return tuple(
        int(item.surveyed)
        for item in peri_scribe.areas.mapping_history(
            frame,
            peri_scribe.areas.DEFAULT_POLICY,
        )
    )
