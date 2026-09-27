"""Classifications, source preferences, and exact geometry shortcuts agree with Lean."""

import itertools

import pytest
import shapely

import peri_scribe.perimeters.border_classification
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.signals
import peri_scribe.perimeters.versions
import tests.formal.helpers.border_classification
import tests.formal.helpers.oracle


def test_classify_preserves_signal_priority_and_source_preference() -> None:
    cases = tests.formal.helpers.border_classification.classifications()
    expected = tests.formal.helpers.oracle.evaluate(
        ["classify " + " ".join(str(int(flag)) for flag in flags) for flags in cases],
        executable="oraclePerimeters",
    )
    for flags, result in zip(cases, expected, strict=True):
        actual = peri_scribe.perimeters.border_classification.classify(
            geometry=tests.formal.helpers.border_classification.geometry_signal(flags),
            extent=peri_scribe.perimeters.classification_data.ExtentSignal(
                wfigs_to_firis_area_ratio=None,
                disagrees=flags[3],
            ),
            identifier=flags[4],
        )
        assert (
            tests.formal.helpers.border_classification.CLASSIFICATIONS.index(
                actual.classification,
            ),
            sum(
                1 << tests.formal.helpers.border_classification.SIGNALS.index(signal)
                for signal in actual.signals
            ),
            int(
                peri_scribe.perimeters.versions.preferred_perimeter_source(actual)
                is peri_scribe.perimeters.versions.WFIGS_PERIMETER,
            ),
        ) == result


def test_geometry_signal_matches_exact_union_and_thresholds() -> None:
    cases = tests.formal.helpers.border_classification.footprint_cases()
    unions = tests.formal.helpers.oracle.evaluate(
        [
            "union " + " ".join(",".join(map(str, part)) for part in parts)
            for parts in cases
        ],
        executable="oraclePerimeters",
    )
    boundaries = tests.formal.helpers.border_classification.boundaries()
    commands = []
    actual_signals = []
    for parts, cells in zip(cases, unions, strict=True):
        shapes = [
            tests.formal.helpers.border_classification.footprint_geometry(part)
            for part in parts
        ]
        union = shapely.union_all(shapes)
        if not shapes:
            continue
        optimized = (
            shapely.GeometryCollection(shapes)
            if all(boundaries.box.contains(shape) for shape in shapes)
            or all(not boundaries.box.intersects(shape) for shape in shapes)
            else union
        )
        assert union.area == len(cells)
        for fraction, absolute, majority in itertools.product(
            (1, 25, 50),
            (0, 3),
            (0, 50, 75),
        ):
            config = tests.formal.helpers.border_classification.planar_config(
                fraction,
                absolute,
                majority,
            )
            actual = peri_scribe.perimeters.signals.geometry_signal(
                optimized,
                boundaries,
                config,
            )
            baseline = peri_scribe.perimeters.signals.geometry_signal(
                union,
                boundaries,
                config,
            )
            assert tests.formal.helpers.border_classification.signal_values(
                actual,
            ) == tests.formal.helpers.border_classification.signal_values(baseline)
            inside = sum(
                cell < tests.formal.helpers.border_classification.BORDER_CELL
                for cell in cells
            )
            commands.append(
                f"geometry {len(cells)} {inside} "
                f"{int(union.distance(boundaries.border))} 2 {fraction} {absolute} "
                f"{majority}",
            )
            actual_signals.append((
                int(actual.crosses),
                int(actual.near),
                int(actual.inside),
            ))
    assert actual_signals == tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oraclePerimeters",
    )


def test_extent_signal_uses_contemporaneous_freshest_source_observations() -> None:
    cases = tests.formal.helpers.border_classification.extent_cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.border_classification.extent_command(case)
            for case in cases
        ],
        executable="oraclePerimeters",
    )
    for case, result in zip(cases, expected, strict=True):
        actual = peri_scribe.perimeters.signals.extent_signal(
            [entry.production() for entry in case],
            peri_scribe.perimeters.classification_data.BorderClassificationConfig(),
        )
        assert (int(actual.disagrees),) == result, case


def test_unioned_observation_geometry_preserves_full_reprojected_signal() -> None:
    config = tests.formal.helpers.border_classification.planar_config(1, 500, 50)
    for split, indices in itertools.product(
        (-50, 50, 200),
        itertools.product(range(5), repeat=2),
    ):
        observations = [
            tests.formal.helpers.border_classification.Extent(
                source=index,
                time=0,
                serial=0,
                shape=shape,
            ).production()
            for index, shape in enumerate(indices)
        ]
        boundaries = peri_scribe.perimeters.classification_data.Boundaries(
            box=shapely.box(-1000, -1000, split, 1000),
            border=shapely.LineString([(split, -1000), (split, 1000)]),
        )
        actual = (
            peri_scribe.perimeters.border_classification.unioned_observation_geometry(
                [*observations, observations[0]],
                boundaries,
            )
        )
        projected = [
            peri_scribe.perimeters.classification_data.reproject_to_california_albers(
                observation.geometry,
                peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                    observation.source
                ],
            )
            for observation in observations
        ]
        expected = shapely.union_all(projected)
        assert tests.formal.helpers.border_classification.signal_values(
            peri_scribe.perimeters.signals.geometry_signal(actual, boundaries, config),
        ) == pytest.approx(
            tests.formal.helpers.border_classification.signal_values(
                peri_scribe.perimeters.signals.geometry_signal(
                    expected,
                    boundaries,
                    config,
                ),
            ),
            abs=1e-5,
        )


def test_geometry_signal_zero_area_obeys_configured_inside_threshold() -> None:
    boundaries = tests.formal.helpers.border_classification.boundaries()
    shapes = (
        shapely.Point(2, 0),
        shapely.Point(10, 0),
        shapely.LineString([(2, 0), (4, 0)]),
        shapely.LineString([(10, 0), (12, 0)]),
        shapely.LineString([(7, 0), (9, 0)]),
        shapely.GeometryCollection([shapely.Point(2, 0), shapely.Point(4, 0)]),
        shapely.GeometryCollection([shapely.Point(10, 0), shapely.Point(12, 0)]),
    )
    commands = []
    actual = []
    for geometry, majority in itertools.product(shapes, (0, 50, 75)):
        signal = peri_scribe.perimeters.signals.geometry_signal(
            geometry,
            boundaries,
            tests.formal.helpers.border_classification.planar_config(1, 3, majority),
        )
        distance = int(geometry.distance(boundaries.border))
        commands.append(
            f"geometry 0 0 {distance} 2 1 3 {majority}",
        )
        actual.append((int(signal.crosses), int(signal.near), int(signal.inside)))
    assert actual == tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oraclePerimeters",
    )
