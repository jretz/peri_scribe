"""Compare full reconciliation with exact evidence and independently measured shapes."""

import dataclasses
import datetime
import itertools
import math

import numpy as np
import shapely

import peri_scribe.models
import peri_scribe.perimeters.versions
import spatial_data.measurements
import tests.formal.helpers.generation
import tests.formal.helpers.perimeter_evidence


ATTRIBUTE_KEYS = (
    "poly_Acres_AutoCalc",
    "attr_IncidentSize",
    "formal_shared",
    "formal_first",
    "formal_second",
)
SCALE = 1_000_000
MEASUREMENT_FIELDS = 2
NULL_CAPTURE = -2
POLICY_KEYS = (
    "source",
    "poly_Source",
    "type",
    "poly_FeatureCategory",
    "poly_PolygonDateTime",
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Entry:
    """Attributes can conflict, disappear, or arrive only in a losing feed."""

    observation: tests.formal.helpers.perimeter_evidence.Observation
    attributes: tuple[int, ...] = (-1, -1, -1, -1, -1)
    policy: tuple[int, ...] = ()

    def policy_values(self) -> tuple[int, ...]:
        """Absence and explicit null have different dictionary-merge consequences.

        Returns:
            Raw primary/alias source and category codes plus capture presence.
        """
        if self.policy:
            return self.policy
        observation = self.observation
        return (
            observation.source,
            observation.source,
            observation.category,
            observation.category,
            observation.capture if observation.capture >= 0 else -2,
        )

    def geometry(self) -> shapely.Geometry:
        """Keep real geodesic measurements within an ordinary United States footprint.

        Returns:
            A geographic rectangle preserving the model's exact overlap ratios.
        """
        observation = self.observation
        return shapely.box(
            -120 + observation.start * 0.00001,
            35,
            -120 + (observation.start + observation.width) * 0.00001,
            35.01,
        )

    def command(self) -> str:
        """Measured area is an input to the policy, while geometry predicates stay real.

        Returns:
            The full oracle record, including every modeled attribute.
        """
        measured = math.floor(
            spatial_data.measurements.area(self.geometry()).m_as("acres") * SCALE,
        )
        attributes = [
            value * SCALE if key < MEASUREMENT_FIELDS and value >= 0 else value
            for key, value in enumerate(self.attributes)
        ]
        return ",".join([
            self.observation.command(),
            str(measured),
            *(str(value) for value in attributes),
            *(str(value) for value in self.policy_values()),
        ])

    def production(self) -> peri_scribe.perimeters.versions.SourceObservation:
        """Retain temporal parsing, GEOS reconciliation, and all source references.

        Returns:
            A real source observation with original numeric attributes.
        """
        observation = self.observation.production()
        attributes = {
            key: value
            for key, value in observation.attributes.items()
            if key not in POLICY_KEYS
        }
        for index, (key, value) in enumerate(
            zip(POLICY_KEYS, self.policy_values(), strict=True),
        ):
            if value == -1:
                continue
            if index < MEASUREMENT_FIELDS:
                attributes[key] = (
                    None if value == 0 else "FIRIS" if value == 1 else "Agency"
                )
            elif key == "poly_PolygonDateTime":
                attributes[key] = (
                    None
                    if value == NULL_CAPTURE
                    else tests.formal.helpers.perimeter_evidence.capture_time(
                        value,
                        same_year=self.observation.same_year,
                    )
                )
            else:
                attributes[key] = None if value == 0 else str(value)
        return dataclasses.replace(
            observation,
            geometry=self.geometry(),
            attributes=attributes
            | {
                key: value
                for key, value in zip(ATTRIBUTE_KEYS, self.attributes, strict=True)
                if value >= 0
            },
        )


def histories() -> list[list[Entry]]:
    """Mixed feeds expose interactions between selection, inheritance, and rejection.

    Returns:
        Boundary histories, input permutations, and seeded longer histories.
    """
    observation_type = tests.formal.helpers.perimeter_evidence.Observation
    cases: list[list[Entry]] = [[]]
    for time, shift, computed, incident in itertools.product(
        (0, 299, 300, 301, 14_400, 14_401, 172_801),
        (0, 4, 6, 25, 26, 1000),
        (-1, 2000),
        (-1, 50_000),
    ):
        cases.append([
            Entry(
                observation=observation_type(identity=0, ancestors=(20,)),
                attributes=(computed, -1, 1, 2, -1),
            ),
            Entry(
                observation=observation_type(identity=1, time=1, feed=1),
                attributes=(-1, incident, 3, -1, 4),
            ),
            Entry(
                observation=observation_type(
                    identity=2,
                    time=time,
                    published=2,
                    start=shift,
                    feed=1,
                    capture=0,
                ),
                attributes=(-1, -1, 5, -1, 6),
            ),
            Entry(
                observation=observation_type(
                    identity=3,
                    time=time + 299,
                    published=3,
                    start=shift,
                    object_id=2,
                    source=1,
                ),
                attributes=(computed, incident, 7, 8, -1),
            ),
        ])
    cases.extend(list(values) for values in itertools.permutations(cases[9]))
    generator = np.random.default_rng(20260928)
    choose = tests.formal.helpers.generation.choose
    cases.extend([
        [
            Entry(
                observation=observation_type(
                    identity=index,
                    time=choose(
                        generator,
                        (0, 1, 299, 300, 301, 14_400, 14_401, 90_000),
                    ),
                    published=int(generator.integers(1, 6)),
                    serial=int(generator.integers(5)),
                    object_id=int(generator.integers(1, 5)),
                    feed=int(generator.integers(2)),
                    source=int(generator.integers(3)),
                    category=int(generator.integers(3)),
                    start=choose(generator, (0, 4, 6, 25, 26, 1000)),
                    capture=choose(generator, (-1, 0, 1, 300, 90_001)),
                    same_year=choose(generator, (False, True)),
                    ancestors=(20 + index,),
                ),
                attributes=(
                    choose(generator, (-1, 0, 100, 1000, 2000)),
                    choose(generator, (-1, 0, 20_000, 50_000)),
                    choose(generator, (-1, 0, 1, 2)),
                    choose(generator, (-1, 0, 1, 2)),
                    choose(generator, (-1, 0, 1, 2)),
                ),
            )
            for index in range(int(generator.integers(1, 8)))
        ]
        for _ in range(500)
    ])
    cases.extend(policy_histories())
    return cases


def policy_histories() -> list[list[Entry]]:
    """Inherited policy metadata can change a later absorption or revision decision.

    Returns:
        Missing, null, primary, alias, and conflicting policy-field histories.
    """
    observation_type = tests.formal.helpers.perimeter_evidence.Observation
    policies = (
        (-1, -1, -1, -1),
        (0, 0, 0, 0),
        (1, 1, 1, 1),
        (2, 2, 2, 2),
        (-1, 1, -1, 1),
        (0, 1, 0, 1),
        (1, -1, 1, -1),
        (1, 2, 1, 2),
    )
    return [
        [
            Entry(
                observation=observation_type(identity=0, time=100, capture=1),
                policy=(*winner, capture),
                attributes=(-1, -1, 1, -1, 0),
            ),
            Entry(
                observation=observation_type(identity=1, time=101, feed=1, capture=1),
                policy=(*loser, 1),
                attributes=(2000, -1, 2, 1, -1),
            ),
            Entry(
                observation=observation_type(
                    identity=2,
                    time=200,
                    start=4,
                    published=3,
                    source=1,
                    category=1,
                ),
                policy=(1, 1, 1, 1, 190),
            ),
            Entry(
                observation=observation_type(
                    identity=3,
                    time=14_601,
                    feed=1,
                    capture=101,
                    published=4,
                ),
                policy=(1, 1, 1, 1, 101),
            ),
        ]
        for winner, loser, capture in itertools.product(
            policies,
            policies,
            (-1, -2, 0, 1, 190),
        )
    ]


def classification(preferred: int) -> peri_scribe.models.FireClassification:
    """Both regional source preferences must traverse the same reconciliation pipeline.

    Args:
        preferred: Zero for FIRIS and one for WFIGS.

    Returns:
        A production classification selecting the requested source.
    """
    return peri_scribe.models.FireClassification(
        classification=(
            peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
            if preferred == 0
            else peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
        ),
        outside_area_fraction=float(preferred),
        inside_area_fraction=float(1 - preferred),
        wfigs_to_firis_area_ratio=None,
        signals=[],
    )


def retained(
    entries: list[peri_scribe.perimeters.versions.SourceObservation],
) -> tuple[int, ...]:
    """Compare winner, effective clock, complete lineage, and conflicting attributes.

    Args:
        entries: Actual full reconciliation output.

    Returns:
        Flat eight-field records in production order.
    """
    values: list[int] = []
    for entry in entries:
        values.extend(tests.formal.helpers.perimeter_evidence.retained([entry]))
        for index, key in enumerate(ATTRIBUTE_KEYS):
            value = entry.attributes.get(key)
            assert value is None or isinstance(value, int)
            values.append(
                value * (SCALE if index < MEASUREMENT_FIELDS else 1)
                if value is not None
                else -1,
            )
        values.extend(policy_result(entry.attributes))
    return tuple(values)


def policy_result(attributes: dict[str, object]) -> tuple[int, ...]:
    """Raw merged field presence remains visible independently of normalization.

    Args:
        attributes: Actual winning dictionary after all merge passes.

    Returns:
        Source/category codes, capture value, and capture-year validity.
    """
    result = []
    for index, key in enumerate(POLICY_KEYS[:-1]):
        value = attributes.get(key)
        result.append(
            -1
            if key not in attributes
            else 0
            if value is None
            else (1 if value == "FIRIS" else 2)
            if index < MEASUREMENT_FIELDS
            else int(str(value)),
        )
    captured = attributes.get(POLICY_KEYS[-1])
    if captured is None:
        result.extend((-2 if POLICY_KEYS[-1] in attributes else -1, 1))
    else:
        assert isinstance(captured, datetime.datetime)
        base = tests.formal.helpers.perimeter_evidence.BASE
        result.extend((
            int((captured.replace(year=base.year) - base).total_seconds()),
            int(captured.year == base.year),
        ))
    return tuple(result)


def before_size_filter(
    entries: list[peri_scribe.perimeters.versions.SourceObservation],
    preferred: int,
) -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Intermediate comparison distinguishes lost provenance from justified rejection.

    Args:
        entries: Source records before any reconciliation.
        preferred: The classification's preferred feed.

    Returns:
        Actual reconciled versions before the final size filter.
    """
    return peri_scribe.perimeters.versions.reconcile_perimeter_versions(
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
            item
            for item in entries
            if item.source_kind is peri_scribe.perimeters.versions.FIRIS_PERIMETER
        ]),
        peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters([
            item
            for item in entries
            if item.source_kind is peri_scribe.perimeters.versions.WFIGS_PERIMETER
        ]),
        classification(preferred),
    )
