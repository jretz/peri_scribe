"""Compare ranked identities and time windows with the executable Lean reference."""

import dataclasses
import datetime
import itertools
import math
import pathlib

import pytest
import shapely

import peri_scribe.models
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.perimeters
import peri_scribe.presentation.views
import peri_scribe.report.gathering
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.kml.parsing
import tests.helpers.factories.peri_scribe.presentation.views
from measurement_units import units


RANKING_COUNT = 480
GROWTH_COUNT = 751
NAME_SCORE_INDEX = 6
UNLIMITED = 50
MISSING = -99999999

ORIGIN = datetime.datetime(2026, 8, 20, tzinfo=datetime.UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ranking:
    """Raw score rows can share a resolved owner without sharing an alias."""

    names: tuple[int, ...]
    visible: int
    values: tuple[int, ...]
    limit: int

    def inputs(
        self,
    ) -> tuple[
        list[peri_scribe.presentation.fire_data.FireSummary],
        peri_scribe.models.FireScores,
    ]:
        """Build actual fires and scores without applying matching or ranking.

        Returns:
            Source fire objects and all saved score rows.
        """
        fires = [
            tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                f"Fire {name}",
                identifiers=frozenset({str(owner), str(owner + 3)}),
            )
            for owner, name in enumerate(self.names)
            if self.visible & (1 << owner)
        ]
        scores = peri_scribe.models.FireScores(
            version="formal",
            fires=[
                tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                    f"Fire {self.names[index % 3]}",
                    None if index == NAME_SCORE_INDEX else str(index),
                    value,
                    str(index),
                )
                for index, value in enumerate(self.values)
            ],
        )
        return fires, scores

    def command(self) -> str:
        """Encode the complete unresolved records for Lean's selection algorithm.

        Returns:
            The oracle request for this raw input.
        """
        fires = " ".join(
            f"{owner},{name},{owner},{owner + 3}"
            for owner, name in enumerate(self.names)
            if self.visible & (1 << owner)
        )
        scores = " ".join(
            f"{'n' if index == NAME_SCORE_INDEX else index},"
            f"{self.names[index % 3]},{value},{index}"
            for index, value in enumerate(self.values)
        )
        return f"top {self.limit} | {fires} | {scores}"


def rankings() -> tuple[Ranking, ...]:
    """Exercise identifier priority, fallback ambiguity, ties and truncation.

    Returns:
        The bounded cross product of raw score and eligibility configurations.
    """
    return tuple(
        Ranking(names=names, visible=visible, values=values, limit=limit)
        for names, visible, values, limit in itertools.product(
            ((0, 1, 2), (0, 0, 1), (0, 0, 0), (2, 1, 0)),
            range(8),
            (
                (1, 2, 3, 4, 5, 6, 7),
                (7, 6, 5, 4, 3, 2, 1),
                (1, 1, 1, 1, 1, 1, 1),
                (100, 0, 0, 99, 0, 0, 98),
                (0, 100, 0, 0, 99, 0, 98),
            ),
            (1, 2, 50),
        )
    )


def check_rankings() -> None:
    """Compare actual selected object ownership with the proved rank/dedup pipeline."""
    cases = rankings()
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oracleOutputs",
    )
    for case, owners in zip(cases, expected, strict=True):
        fires, scores = case.inputs()
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                peri_scribe.presentation.views,
                "TOP_FIRE_COUNT",
                case.limit,
            )
            selected = peri_scribe.presentation.views.top_fires(fires, scores)
        assert tuple(min(map(int, fire.identifiers)) for fire in selected) == owners
        assert len({id(fire) for fire in selected}) == len(selected)


def check_exclusion_before_limit() -> None:
    """Excluded scores cannot consume a showable fire's slot in a limited view."""
    excluded = peri_scribe.presentation.views.TOP_FIRE_COUNT + 10
    fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
        "Fire 0",
        identifiers=frozenset({"0"}),
    )
    rows = [(index + 1, 1, 200 - index) for index in range(excluded)] + [(0, 0, 1)]
    scores = peri_scribe.models.FireScores(
        version="formal",
        fires=[
            tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                f"Fire {name}",
                str(identifier),
                value,
                "",
            )
            for identifier, name, value in rows
        ],
    )
    request = " ".join(
        f"{identifier},{name},{value},{serial}"
        for serial, (identifier, name, value) in enumerate(rows)
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [f"top {peri_scribe.presentation.views.TOP_FIRE_COUNT} | 0,0,0 | {request}"],
        executable="oracleOutputs",
    )[0]
    actual = peri_scribe.presentation.views.top_fires([fire], scores)
    assert tuple(int(min(item.identifiers)) for item in actual) == expected
    assert actual == [fire]


def growth_histories() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Dates bracket the cutoff, current instant, future, and equal-time corrections.

    Returns:
        Integer elapsed seconds and stored acreage in source order.
    """
    result = [()]
    for times, areas in itertools.product(
        (
            (-172801, -172800, 0),
            (-172800, -1, 1),
            (-172799, 0, 1),
            (1, 2, 3),
            (-1, 0, 0),
            (0, -172800, -1),
        ),
        itertools.product((0, 1, 999, 1000, 1001), repeat=3),
    ):
        result.append(tuple(zip(times, areas, strict=True)))
    return tuple(result)


def check_growth() -> None:
    """Check latest/baseline evidence and both real growth-ranking selectors."""
    cases = growth_histories()
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "growth 0 172800 | " + " ".join(f"{time},{area}" for time, area in rows)
            for rows in cases
        ],
        executable="oracleOutputs",
    )
    for rows, (growth, baseline, acres_visible, percent_visible) in zip(
        cases,
        expected,
        strict=True,
    ):
        fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
            "Measured",
            perimeters=tuple(
                peri_scribe.presentation.perimeters.Perimeter(
                    geometry=shapely.box(0, 0, 1, 1),
                    observation_time=ORIGIN + datetime.timedelta(seconds=time),
                    area=area * units.acres,
                )
                for time, area in rows
            ),
        )
        actual, percent = peri_scribe.presentation.views.fire_growth(fire, ORIGIN)
        if growth == MISSING:
            assert actual is None
            assert percent is None
            continue
        assert actual is not None
        assert actual.m_as("acres") == growth
        if baseline <= 0:
            assert percent is None
        else:
            assert percent is not None
            assert math.isclose(percent.m_as("percent"), 100 * growth / baseline)
        assert bool(
            peri_scribe.presentation.views.fast_growing_fires_by_acres([fire], ORIGIN),
        ) == bool(acres_visible)
        assert bool(
            peri_scribe.presentation.views.fast_growing_fires_by_percent(
                [fire],
                ORIGIN,
            ),
        ) == bool(percent_visible)


def check_windows() -> None:
    """Compare inclusive cutoff and future exclusion in personnel/discovery views."""
    for width, discovery in ((432000, True), (604800, False)):
        times = (-width - 1, -width, -width + 1, -1, 0, 1)
        expected = tests.formal.helpers.oracle.evaluate(
            [f"window 0 {width} | " + " ".join(map(str, times))],
            executable="oracleOutputs",
        )[0]
        for observed, accepted in zip(times, expected, strict=True):
            description = peri_scribe.presentation.descriptions.FireDescription(
                discovery_time=ORIGIN + datetime.timedelta(seconds=observed),
                observation_time=ORIGIN + datetime.timedelta(seconds=observed),
                total_personnel=0,
            )
            fire = tests.helpers.factories.peri_scribe.presentation.views.active_fire(
                "Window",
                description=description,
                identifiers=frozenset({"window"}),
            )
            scores = peri_scribe.models.FireScores(
                version="formal",
                fires=[
                    tests.helpers.factories.peri_scribe.presentation.views.score_entry(
                        "Window",
                        "window",
                        100,
                        "",
                    ),
                ],
            )
            actual = (
                peri_scribe.presentation.views.new_notable_fires([fire], scores, ORIGIN)
                if discovery
                else peri_scribe.presentation.views.most_personnel_fires([fire], ORIGIN)
            )
            assert actual == ([fire] if accepted else [])


def check_associated_outputs(directory: pathlib.Path) -> None:
    """Track source score and explanation through real history preparation and reports.

    Args:
        directory: Isolated report directory with no external cities dataset.
    """
    cases = tuple(case for case in rankings() if case.visible)
    expected = tests.formal.helpers.oracle.evaluate(
        ["associations | " + case.command().split("|", 1)[1] for case in cases],
        executable="oracleOutputs",
    )
    for case, outcome in zip(cases, expected, strict=True):
        sources, scores = case.inputs()
        index = peri_scribe.models.FireIndex(
            version="formal",
            fires=[
                tests.helpers.factories.peri_scribe.kml.parsing.fire_index_entry(
                    fire.name,
                    "active",
                    identifier=min(fire.identifiers),
                    aliases=sorted(fire.identifiers),
                )
                for fire in sources
            ],
        )
        perimeters = tests.helpers.factories.peri_scribe.kml.parsing.geometry_frame([
            (min(fire.identifiers), fire.name, shapely.box(0, 0, 1, 1))
            for fire in sources
        ])
        empty = perimeters.iloc[:0]
        fires = peri_scribe.presentation.fire_data.fire_summaries(
            index,
            perimeters,
            empty,
            empty,
            scores=scores,
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                peri_scribe.presentation.views,
                "TOP_FIRE_COUNT",
                case.limit,
            )
            prepared = peri_scribe.report.gathering.report_from_fires(
                fires,
                scores,
                directory,
            )
        expected_rows = tuple(
            zip(outcome[::3], outcome[1::3], outcome[2::3], strict=True),
        )
        assert tuple(
            (int(entry.identifier or "-1"), entry.score) for entry in prepared.top_fires
        ) == tuple(
            (owner, value) for owner, value, _serial in expected_rows[: case.limit]
        )
        by_owner = {owner: serial for owner, _value, serial in expected_rows}
        for fire in fires:
            owner = min(map(int, fire.identifiers))
            assert fire.description is not None
            assert fire.description.of_note == (
                str(by_owner[owner]) if owner in by_owner else None
            )
