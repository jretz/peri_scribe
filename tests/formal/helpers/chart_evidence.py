"""Independent source streams and actual SVG paths retain the proved evidence."""

import dataclasses
import datetime
import itertools
import math

import defusedxml.ElementTree
import geopandas
import pytest

import peri_scribe.areas
import peri_scribe.geo.measurements
import peri_scribe.incidents
import peri_scribe.kml.plot_data
import svg_charts.models
import svg_charts.time_series
import tests.formal.helpers.oracle
import tests.helpers.factories.geography
from measurement_units import units


EPOCH = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)
SVG_NAMESPACE = "{http://www.w3.org/2000/svg}"
HISTORY_CASE_COUNT = 1849
SEGMENT_CASE_COUNT = 1022


def moment(time: int) -> datetime.datetime:
    """Integral source times retain their exact ordering in real aware datetimes.

    Args:
        time: Elapsed UTC seconds.

    Returns:
        The corresponding timestamp.
    """
    return EPOCH + datetime.timedelta(seconds=time)


def update(
    time: int,
    value: int | None,
    serial: int,
) -> peri_scribe.incidents.IncidentUpdate:
    """Sparse incident observations preserve explicit zero and absent containment.

    Args:
        time: The report time in seconds.
        value: The reported containment percentage, or missing.
        serial: The source row identity.

    Returns:
        An independently dated actual report.
    """
    return peri_scribe.incidents.IncidentUpdate(
        observation_time=moment(time),
        report_time=None,
        confirmed=False,
        source="wfigs_location",
        source_file=f"report-{serial}.gpkg",
        serial=serial,
        measurements={"personnel": 10}
        if value is None
        else {"percent_contained": value},
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class History:
    """Unsorted histories can include duplicate times and later source corrections."""

    lengths: tuple[tuple[int, int], ...]
    percentages: tuple[tuple[int, int], ...]

    def command(self) -> str:
        """Lean receives raw events before any latest-value or time-union operation.

        Returns:
            The independent-ledger oracle request.
        """
        return (
            "estimates | "
            + " ".join(f"{time},{value}" for time, value in self.lengths)
            + " | "
            + " ".join(f"{time},{value}" for time, value in self.percentages)
        )


def histories() -> tuple[History, ...]:
    """Cross products cover missing sides, simultaneous updates, reordering and ties.

    Returns:
        All streams of up to two source observations over the selected boundaries.
    """
    lengths = tuple(itertools.product((-2, 0, 2), (0, 10)))
    percentages = tuple(itertools.product((-2, 0, 2), (0, 100)))
    return tuple(
        History(lengths=length_history, percentages=percent_history)
        for length_history, percent_history in itertools.product(
            (
                (),
                *itertools.product(lengths, repeat=1),
                *itertools.product(lengths, repeat=2),
            ),
            (
                (),
                *itertools.product(percentages, repeat=1),
                *itertools.product(percentages, repeat=2),
            ),
        )
    )


def check_independent_histories() -> None:
    """Actual containment estimates agree with the executable source-selection fold."""
    cases = histories()
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oraclePolicyDetails",
    )
    empty = tests.helpers.factories.geography.empty_frame()
    for index, (case, result) in enumerate(zip(cases, expected, strict=True)):
        length_unit = ("miles", "kilometers", "feet")[index % 3]
        measurements = (
            *(
                peri_scribe.kml.plot_data.ExteriorMeasurement(
                    observation_time=moment(time),
                    length=(value * units.miles).to(length_unit),
                )
                for time, value in case.lengths
            ),
            peri_scribe.kml.plot_data.ExteriorMeasurement(
                observation_time=moment(1),
                length=None,
            ),
            peri_scribe.kml.plot_data.ExteriorMeasurement(
                observation_time=None,
                length=999 * units.miles,
            ),
        )
        updates = (
            *(
                update(time, value, serial)
                for serial, (time, value) in enumerate(case.percentages)
            ),
            update(1, None, 99),
        )
        actual = peri_scribe.kml.plot_data.contained_perimeter_points(
            empty,
            measurements,
            updates=updates,
        )
        assert [point.observation_time for point in actual] == [
            moment(time) for time in result[::3]
        ], case
        assert [point.value for point in actual] == pytest.approx([
            length * percent / 100
            for length, percent in zip(result[1::3], result[2::3], strict=True)
        ]), case


@dataclasses.dataclass(frozen=True, kw_only=True)
class Point:
    """Distinct identities survive repeated values and simultaneous observations."""

    identity: int
    time: int
    value: int
    dashed: bool

    def command(self) -> str:
        """Send source identity and style without applying segmentation in Python.

        Returns:
            The complete source point.
        """
        return f"{self.identity},{self.time},{self.value},{int(self.dashed)}"

    def estimate(self) -> peri_scribe.areas.AreaEstimate:
        """Real plot construction decides the style from the selected evidence source.

        Returns:
            A mapped or reported estimate expressed in actual area units.
        """
        return peri_scribe.areas.AreaEstimate(
            time=moment(self.time),
            observation_time=moment(self.time - 60),
            area=(self.value * 1000 * units.acres).to("meters ** 2"),
            source=peri_scribe.areas.AreaSource.REPORTED
            if self.dashed
            else peri_scribe.areas.AreaSource.MAPPED,
            source_file=f"source-{self.identity}.gpkg",
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Segmentation:
    """Variable-size oracle groups retain shared endpoints explicitly."""

    segments: tuple[tuple[int, tuple[int, ...]], ...]
    legend: tuple[int, ...]


def decoded_segments(result: tuple[int, ...]) -> Segmentation:
    """Decode only structural lengths; all semantic choices come from Lean.

    Args:
        result: The oracle's length-prefixed sequence.

    Returns:
        Styled point identities and the visible legend styles.
    """
    segment_count = result[0]
    cursor = 1
    segments = []
    for _index in range(segment_count):
        style, count = result[cursor : cursor + 2]
        cursor += 2
        segments.append((style, result[cursor : cursor + count]))
        cursor += count
    legend_count = result[cursor]
    legend = result[cursor + 1 :]
    assert len(legend) == legend_count
    return Segmentation(segments=tuple(segments), legend=legend)


def point_histories() -> tuple[tuple[Point, ...], ...]:
    """Every style run through eight points is combined with repeated timestamps.

    Returns:
        Source histories including isolated points and immediately alternating styles.
    """
    return tuple(
        tuple(
            Point(
                identity=index,
                time=(index // 2 if simultaneous else index) * 86400 + 18000,
                value=1 + index % 3,
                dashed=style,
            )
            for index, style in enumerate(styles)
        )
        for count in range(9)
        for styles in itertools.product((False, True), repeat=count)
        for simultaneous in (False, True)
    )


def area_series(points: tuple[Point, ...]) -> svg_charts.models.PlotSeries:
    """Actual fire plots translate selected area evidence to displayed source styles.

    Args:
        points: Selected evidence whose source semantics the oracle receives.

    Returns:
        The actual plot's area series, before SVG serialization.
    """
    empty = tests.helpers.factories.geography.empty_frame()
    prepared = peri_scribe.areas.PreparedHistory(
        updates=(),
        estimates=tuple(point.estimate() for point in points),
        latest_area=None,
        historical_area=None,
    )
    plots = peri_scribe.kml.plot_data.fire_plots(empty, empty, history=prepared)
    return plots[0].series[0]


def check_svg(
    series: svg_charts.models.PlotSeries,
    expected: Segmentation,
) -> None:
    """Saved SVG paths and legend swatches retain exactly the proved source edges.

    Args:
        series: Actual area plot points and labels.
        expected: Oracle-selected segment identities and legend styles.
    """
    layout = svg_charts.time_series.plot_layout((series,))
    document = defusedxml.ElementTree.fromstring(
        svg_charts.time_series.draw_plot((series,)),
    )
    paths = list(document.iter(SVG_NAMESPACE + "path"))
    assert len(paths) == len(expected.segments)
    for path, (style, identities) in zip(paths, expected.segments, strict=True):
        commands = path.attrib["d"].split()
        assert commands[::3] == ["M", *["L"] * (len(identities) - 1)]
        assert path.get("stroke-dasharray") == ("5 3" if style else None)
        expected_coordinates = [
            coordinate
            for identity in identities
            for coordinate in (
                round(layout.x_of(series.points[identity].observation_time), 1),
                round(layout.y_of(series.points[identity].value), 1),
            )
        ]
        actual_coordinates = [
            float(value) for index, value in enumerate(commands) if index % 3
        ]
        assert actual_coordinates == expected_coordinates
    swatches = [
        line
        for line in document.iter(SVG_NAMESPACE + "line")
        if line.get("stroke") == series.color
    ]
    assert tuple(
        int(line.get("stroke-dasharray") is not None) for line in swatches
    ) == (expected.legend)
    labels = [
        element.text
        for element in document.iter(SVG_NAMESPACE + "text")
        if element.get("y") == f"{svg_charts.time_series.LEGEND_BASELINE_Y:.1f}"
    ]
    assert labels == [
        series.dashed_label if style else series.label for style in expected.legend
    ]


def check_segment_histories(*, rendered: bool) -> None:
    """Source-style changes reach the final artifact through real fire plot creation.

    Args:
        rendered: Whether to inspect serialized SVG paths or the in-memory segments.
    """
    cases = point_histories()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "segments | " + " ".join(point.command() for point in points)
            for points in cases
        ],
        executable="oraclePolicyDetails",
    )
    for points, result in zip(cases, expected, strict=True):
        oracle = decoded_segments(result)
        series = area_series(points)
        assert len(series.points) == len(points)
        for original, actual in zip(points, series.points, strict=True):
            assert actual.observation_time == moment(original.time)
            assert math.isclose(actual.value, original.value)
            assert int(actual.style) == int(original.dashed)
        if rendered:
            if series.points:
                check_svg(series, oracle)
        else:
            identities = {id(point): index for index, point in enumerate(series.points)}
            actual = svg_charts.time_series.line_segments(series.points)
            assert (
                tuple(
                    (int(style), tuple(identities[id(point)] for point in segment))
                    for segment, style in actual
                )
                == oracle.segments
            )
            legend = svg_charts.time_series.legend_entries((series,))
            assert tuple(int(entry.style) for entry in legend) == oracle.legend


def check_stored_history_composition() -> None:
    """Stored perimeter lengths and parsed incident reports feed the same ledger.

    Percentages are already reconciled by the separately checked incident-history
    policy. This adapter retains the actual frame parsing and complete plot builder.
    """
    cases = (
        History(lengths=((0, 10), (2, 20)), percentages=((-1, 30), (1, 70), (3, 100))),
        History(lengths=((-2, 0), (1, 10), (3, 5)), percentages=((0, 0), (2, 25))),
        History(lengths=((0, 10),), percentages=((2, 100),)),
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oraclePolicyDetails",
    )
    for case, result in zip(cases, expected, strict=True):
        perimeters = geopandas.GeoDataFrame(
            {
                "observation_time": [
                    moment(time).isoformat() for time, _ in case.lengths
                ],
                peri_scribe.geo.measurements.EXTERIOR_COLUMN: [
                    (value * units.miles).m_as("meters") for _, value in case.lengths
                ],
            },
            geometry=[None] * len(case.lengths),
            crs="EPSG:4326",
        )
        incident_rows = geopandas.GeoDataFrame(
            {
                "observation_time": [
                    moment(time).isoformat() for time, _ in case.percentages
                ],
                "percent_contained": [value for _, value in case.percentages],
                "report_confirmed": [False] * len(case.percentages),
            },
            geometry=[None] * len(case.percentages),
            crs="EPSG:4326",
        )
        empty = tests.helpers.factories.geography.empty_frame()
        actual = peri_scribe.kml.plot_data.contained_perimeter_points(
            perimeters,
            point_rows=empty,
            incident_rows=incident_rows,
        )
        assert [point.observation_time for point in actual] == [
            moment(time) for time in result[::3]
        ]
        assert [point.value for point in actual] == pytest.approx([
            length * percent / 100
            for length, percent in zip(result[1::3], result[2::3], strict=True)
        ])
