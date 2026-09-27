"""Exact footprint histories connect source attribution to actual displayed rings."""

import dataclasses
import datetime
import hashlib
import itertools
import math
import typing
import unittest.mock

import numpy as np
import pandas as pd
import pytest
import shapely

import peri_scribe.fires.differential
import peri_scribe.geo.measurements
import peri_scribe.geo.parsing
import peri_scribe.kml.colormap
import peri_scribe.perimeters.progression
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import spatial_data.measurements
from measurement_units import units


ROW_WIDTH = 24
EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Source:
    """Metadata remains distinct even when neighboring perimeters show no growth."""

    identity: int
    shape: int
    time: int | None
    values: tuple[int | None, ...]

    def command(self) -> str:
        """Missing and zero measurements require distinct oracle representations.

        Returns:
            One complete source observation in the oracle protocol.
        """
        return ",".join(
            "n" if value is None else str(value)
            for value in (self.identity, self.time, self.shape, *self.values)
        )

    def attributes(self) -> dict[str, object]:
        """Actual parsing must accept the source's numeric strings and missing forms.

        Returns:
            Distinct provenance and the four cumulative measurement fields.
        """
        missing = (None, float("nan"), pd.NA, "unknown")
        return {
            "formal_identity": self.identity,
            "source_file": f"source-{self.identity}.gpkg",
            "source_objectid": 101 + self.identity * 97,
            "observation_time": None
            if self.time is None
            else (EPOCH + datetime.timedelta(hours=self.time)).isoformat(),
        } | {
            key: missing[(self.identity + index) % len(missing)]
            if value is None
            else str(value)
            if self.identity % 2 == 0
            else value
            for index, (key, value) in enumerate(
                zip(
                    peri_scribe.fires.differential.GROWTH_COLUMNS,
                    self.values,
                    strict=True,
                ),
            )
        }


def footprint(mask: int, *, small: bool) -> shapely.Geometry:
    """Disjoint cells give exact set membership while retaining real geodesic areas.

    Args:
        mask: A four-cell footprint.
        small: Whether cells should straddle the one-square-meter visibility threshold.

    Returns:
        A real WGS84 polygon union, including an empty geometry for no cells.
    """
    widths = (0.000002, 0.00001, 0.00002, 0.000003) if small else (0.001,) * 4
    return shapely.union_all([
        shapely.box(-120 + cell * 0.01, 35, -120 + cell * 0.01 + width, 35 + width)
        for cell, width in enumerate(widths)
        if mask & (1 << cell)
    ])


def histories() -> list[list[Source]]:
    """Exhaustive short shapes combine with longer sparse attribute histories.

    Returns:
        Shrinkage, repeated observations, missing fields, and seeded longer histories.
    """
    generator = np.random.default_rng(20261003)
    shapes = [list(values) for values in itertools.product(range(8), repeat=3)]
    shapes.extend([
        [],
        [0],
        [15],
        [0, 0, 0],
        [1, 1, 3, 3, 7, 7, 15, 15],
        [15, 7, 3, 1, 0],
        [1, 0, 3, 0, 15],
        [1, 3, 7, 15],
    ])
    shapes.extend(
        list(map(int, generator.integers(0, 16, int(generator.integers(1, 10)))))
        for _ in range(100)
    )
    values = (None, None, 0, -5, 3, 12, 100)
    return [
        [
            Source(
                identity=index,
                shape=shape,
                time=None if (case + index) % 3 == 0 else index // 2 - 2,
                values=tuple(
                    values[int(generator.integers(len(values)))] for _ in range(4)
                ),
            )
            for index, shape in enumerate(history)
        ]
        for case, history in enumerate(shapes)
    ]


def command(
    sources: list[Source],
    *,
    small: bool,
    omitted: tuple[int, ...] = (),
) -> str:
    """Geodesic measurements are explicit inputs to the ideal visibility policy.

    Args:
        sources: Complete observations, including those that will not emit a ring.
        small: The geometric scale used by the actual execution.
        omitted: Candidate positions suppressed by a numerical geometry backend.

    Returns:
        A request for the proved correction, attribution, sparse deltas, and selection.
    """
    areas = [
        math.ceil(
            spatial_data.measurements.area(footprint(mask, small=small)).m_as(
                "meters ** 2",
            )
            * 1_000_000,
        )
        for mask in range(16)
    ]
    return " ".join([
        "rows",
        ",".join(map(str, omitted)) or "n",
        ",".join(map(str, areas)),
        *(source.command() for source in sources),
    ])


def records(response: tuple[int, ...]) -> list[tuple[int, ...]]:
    """Fixed-size records prevent field misalignment from hiding an oracle mismatch.

    Args:
        response: One complete oracle response.

    Returns:
        All candidate rows, including omitted candidates with retained source evidence.
    """
    assert len(response) % ROW_WIDTH == 0
    return [
        response[index : index + ROW_WIDTH]
        for index in range(0, len(response), ROW_WIDTH)
    ]


def production(
    sources: list[Source],
    *,
    small: bool,
    candidates: list[tuple[int, ...]],
    omitted: tuple[int, ...] = (),
) -> list[dict[str, object]]:
    """The rare empty-sliver branch is a separate controlled backend outcome.

    Args:
        sources: The original chronological observations.
        small: The geographic scale used for real GEOS operations.
        candidates: The model's complete candidate lineage before emission.
        omitted: Original positions whose difference construction should return empty.

    Returns:
        Actual rows after correction, representative selection, and drawn-area storage.
    """
    attributes = [source.attributes() for source in sources]
    geometries = [
        None if source.shape == 0 else footprint(source.shape, small=small)
        for source in sources
    ]
    if not omitted:
        return peri_scribe.fires.differential.differential_rows_for_fire(
            attributes,
            geometries,
        )
    original = peri_scribe.fires.differential.geometry_difference
    positions = iter(row[0] for row in candidates)

    def difference(
        current: shapely.Geometry | None,
        previous: shapely.Geometry | None,
    ) -> shapely.Geometry | None:
        """Retain real differences except the selected environmental failures.

        Args:
            current: The current corrected footprint.
            previous: The immediately preceding corrected footprint.

        Returns:
            The actual GEOS difference or the injected numerical-empty result.
        """
        return None if next(positions) in omitted else original(current, previous)

    with unittest.mock.patch.object(
        peri_scribe.fires.differential,
        "geometry_difference",
        side_effect=difference,
    ):
        return peri_scribe.fires.differential.differential_rows_for_fire(
            attributes,
            geometries,
        )


def assert_rows(
    sources: list[Source],
    expected: list[tuple[int, ...]],
    actual: list[dict[str, object]],
    *,
    small: bool,
) -> None:
    """Compare geometry, lineage, and sparse deltas independently of Python selection.

    Args:
        sources: Original evidence by unique identity.
        expected: All candidate records emitted by the proved Lean definitions.
        actual: Rows returned by the production differential transform.
        small: The fixture's geodesic scale.
    """
    emitted = [row for row in expected if row[4]]
    assert len(actual) == len(emitted)
    cumulative = 0
    cumulative_shapes = {}
    for row in expected:
        cumulative |= row[3]
        cumulative_shapes[row[0]] = cumulative
    for row, result in zip(actual, emitted, strict=True):
        source = sources[result[2]]
        assert row["formal_identity"] == source.identity
        assert row["source_file"] == source.attributes()["source_file"]
        assert row["source_objectid"] == source.attributes()["source_objectid"]
        assert row["observation_time"] == source.attributes()["observation_time"]
        geometry = typing.cast("shapely.Geometry", row["geometry"])
        assert geometry.equals(footprint(result[3], small=small))
        for index, key in enumerate(peri_scribe.fires.differential.GROWTH_COLUMNS):
            offset = 8 + 4 * index
            value = result[offset + 1] if result[offset] else None
            difference = result[offset + 3] if result[offset + 2] else None
            assert peri_scribe.geo.parsing.numeric_value(row[key]) == value
            assert row[f"{key}_differential"] == difference
        area = spatial_data.measurements.area(footprint(result[3], small=small))
        assert row[peri_scribe.geo.measurements.AREA_COLUMN] == pytest.approx(
            area.m_as("meters ** 2"),
        )
        assert row["area_acres_from_geometry_differential"] == pytest.approx(
            area.m_as("acres"),
        )
        assert row["area_acres_from_geometry"] == pytest.approx(
            spatial_data.measurements.area(
                footprint(
                    cumulative_shapes[result[0]],
                    small=small,
                ),
            ).m_as("acres"),
        )
    assert_visible_sequence(emitted, actual)


def assert_visible_sequence(
    expected: list[tuple[int, ...]],
    actual: list[dict[str, object]],
) -> None:
    """Stored measurements and presentation must share the model-selected ring sequence.

    Args:
        expected: Model records for the emitted rows.
        actual: Production rows in the same progression order.
    """
    selected = [row for row, result in zip(actual, expected, strict=True) if result[5]]
    digest = hashlib.sha256()
    previous_area = 0.0
    shapes: list[shapely.Geometry] = []
    for row in selected:
        geometry = typing.cast("shapely.Geometry", row["geometry"])
        content = shapely.to_wkb(geometry, include_srid=True)
        digest.update(len(content).to_bytes(8))
        digest.update(content)
        shapes.append(geometry)
        area = spatial_data.measurements.area(shapely.union_all(shapes)).m_as(
            "meters ** 2",
        )
        assert row[
            peri_scribe.perimeters.progression.ADDED_AREA_COLUMN
        ] == pytest.approx(
            max(0.0, area - previous_area),
        )
        previous_area = area
    rings = []
    for row, result in zip(actual, expected, strict=True):
        assert (peri_scribe.perimeters.progression.SEQUENCE_COLUMN in row) == bool(
            result[5],
        )
        if result[5]:
            assert (
                row[peri_scribe.perimeters.progression.SEQUENCE_COLUMN]
                == digest.hexdigest()
            )
        perimeter = peri_scribe.presentation.perimeters.Perimeter(
            geometry=typing.cast("shapely.Geometry", row["geometry"]),
            observation_time=peri_scribe.geo.parsing.observation_time_from(
                row["observation_time"],
            ),
            area=typing.cast("float", row[peri_scribe.geo.measurements.AREA_COLUMN])
            * units.Unit("meters ** 2"),
        )
        ring = peri_scribe.presentation.fire_data.progression_ring(perimeter)
        if ring is not None:
            rings.append(ring)
    displayed = [
        ring.geometry
        for ring, _color in peri_scribe.kml.colormap.progression_ring_colors(rings)
    ]
    assert displayed == [row["geometry"] for row in selected]
