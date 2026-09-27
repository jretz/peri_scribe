"""Compare real source validation with the checked relational coverage contract."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import typing

import geopandas
import pandas as pd
import shapely

import peri_scribe.sources.validation
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.sources.feed_types


COLUMNS = ("name", "size", "extra")


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scalar:
    """The fixture declares semantic equivalence without production normalization."""

    value: object
    token: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Shape:
    """Equivalent wrappers share a declared topological token."""

    value: shapely.Geometry | None
    token: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Row:
    """Preserve every row occurrence before any OBJECTID indexing."""

    identifier: int
    attributes: tuple[Scalar, ...]
    shape: Shape


@dataclasses.dataclass(frozen=True, kw_only=True)
class Frame:
    """Declared schema and CRS remain part of empty source snapshots."""

    rows: tuple[Row, ...]
    columns: tuple[int, ...] = (0, 1)
    reference: int | None = 4326

    def dataframe(self) -> geopandas.GeoDataFrame:
        """Construct real dataframes while preserving Python scalar representations.

        Returns:
            Source rows with the exact declared schema, shape, and coordinate reference.
        """
        return geopandas.GeoDataFrame(
            {
                "OBJECTID": [row.identifier for row in self.rows],
                **{
                    COLUMNS[column]: pd.Series(
                        [row.attributes[column].value for row in self.rows],
                        dtype=object,
                    )
                    for column in self.columns
                },
            },
            geometry=[row.shape.value for row in self.rows],
            crs=self.reference,
        )

    def text(self) -> str:
        """Serialize raw semantic tokens, leaving all comparison choices to Lean.

        Returns:
            The frame's three protocol sections.
        """
        return "|".join((
            "n" if self.reference is None else str(self.reference),
            " ".join(map(str, self.columns)),
            " ".join(
                ",".join(
                    map(
                        str,
                        (
                            row.identifier,
                            row.shape.token,
                            *itertools.chain.from_iterable(
                                (column, row.attributes[column].token)
                                for column in self.columns
                            ),
                        ),
                    ),
                )
                for row in self.rows
            ),
        ))


def scalars() -> tuple[Scalar, ...]:
    """Missing spelling and subsecond date precision intentionally normalize together.

    Returns:
        Independent raw values with their expected normalized equality classes.
    """
    now = datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC)
    return (
        Scalar(value="a", token=1),
        Scalar(value="b", token=2),
        *(Scalar(value=value, token=3) for value in (None, pd.NA, float("nan"))),
        Scalar(value=now, token=4),
        Scalar(value=now.replace(microsecond=999999), token=4),
        Scalar(value=now + datetime.timedelta(seconds=1), token=5),
        Scalar(value=1, token=6),
        Scalar(value=1.0, token=6),
    )


def shapes() -> tuple[Shape, ...]:
    """Topological equality admits wrapper and ring-order changes but retains absence.

    Returns:
        Missing, empty, point, and polygon representations with declared equality.
    """
    polygon = shapely.Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])
    return (
        Shape(value=None, token=0),
        Shape(value=shapely.Point(), token=1),
        Shape(value=shapely.Polygon(), token=1),
        Shape(value=shapely.Point(1, 1), token=2),
        Shape(value=shapely.Point(2, 2), token=3),
        Shape(value=polygon, token=4),
        Shape(value=shapely.reverse(polygon), token=4),
        Shape(value=shapely.MultiPolygon([polygon]), token=4),
    )


def frames() -> tuple[Frame, ...]:
    """Cross product inputs expose content, multiplicity, schema, CRS, and ordering.

    Returns:
        Reusable source snapshots for pairwise coverage checks.
    """
    values = scalars()
    geometry = shapes()
    first = Row(
        identifier=1,
        attributes=(values[0], values[-1], values[1]),
        shape=geometry[3],
    )
    second = dataclasses.replace(first, identifier=2)
    changed = dataclasses.replace(first, attributes=(values[1], values[0], values[0]))
    histories = (
        (),
        (first,),
        (second,),
        (first, second),
        (second, first),
        (first, first),
        (changed, first),
        (first, changed),
        (first, second, second),
    )
    result = [Frame(rows=history) for history in histories]
    result.extend(
        Frame(rows=rows, columns=columns, reference=reference)
        for rows, columns, reference in itertools.product(
            ((), (first,)),
            ((), (0,), (1,), (1, 0), (0, 1, 2)),
            (None, 4326, 3857),
        )
    )
    result.extend(
        Frame(rows=(dataclasses.replace(first, attributes=(value, value, value)),))
        for value in values
    )
    result.extend(
        Frame(rows=(dataclasses.replace(first, shape=shape),)) for shape in geometry
    )
    return tuple(result)


def packed(values: typing.Iterable[int]) -> tuple[int, ...]:
    """Diagnostic collections have set semantics and stable protocol ordering.

    Args:
        values: Concrete reported IDs or column tokens.

    Returns:
        A length-prefixed sorted collection.
    """
    ordered = sorted(values)
    return (len(ordered), *ordered)


def outcome(
    result: peri_scribe.sources.validation.FeedValidationResult,
) -> tuple[int, ...]:
    """Retain every public validation decision and diagnostic in the comparison.

    Args:
        result: The actual production report.

    Returns:
        The complete oracle response shape.
    """
    return (
        int(not result.has_problems),
        int(result.coordinate_reference_mismatch),
        *packed(result.missing_object_ids),
        *packed(result.mismatched_object_ids),
        *packed(COLUMNS.index(name) for name in result.columns_missing_from_stored),
        *packed(result.duplicate_complete_object_ids),
        *packed(result.duplicate_stored_object_ids),
    )


def check_frames() -> int:
    """Successful indexed reports must match the compiled relational coverage model.

    Returns:
        The number of complete dataframe-pair comparisons.
    """
    catalogue = frames()
    pairs = tuple(itertools.product(range(len(catalogue)), repeat=2))
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"validate|{catalogue[first].text()}|{catalogue[second].text()}"
            for first, second in pairs
        ],
        executable="oracleSourceValidation",
    )
    concrete = tuple(frame.dataframe() for frame in catalogue)
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    for (first, second), answer in zip(pairs, expected, strict=True):
        result = peri_scribe.sources.validation.validate_feed(
            feed,
            concrete[first],
            concrete[second],
        )
        assert result.complete_feature_count == len(catalogue[first].rows)
        assert outcome(result) == answer, (first, second, result)
    return len(pairs)


def check_missing_store() -> int:
    """Missing ID schema cannot be mistaken for a complete stored snapshot.

    Returns:
        Comparisons with absent stores and stores missing their primary key.
    """
    catalogue = frames()
    missing = Frame(rows=(), columns=(), reference=None)
    expected = tests.formal.helpers.oracle.evaluate(
        [f"validate|{frame.text()}|{missing.text()}" for frame in catalogue],
        executable="oracleSourceValidation",
    )
    feed = tests.helpers.factories.peri_scribe.sources.feed_types.change_feed()
    for frame, answer in zip(catalogue, expected, strict=True):
        concrete = frame.dataframe()
        for stored in (None, geopandas.GeoDataFrame(concrete.drop(columns="OBJECTID"))):
            result = peri_scribe.sources.validation.validate_feed(
                feed,
                concrete,
                stored,
            )
            assert outcome(result) == answer
    return len(catalogue) * 2
