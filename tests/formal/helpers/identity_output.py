"""Compose real grouping, alias selection, histories, and presentation consumers."""

from __future__ import annotations

import dataclasses
import datetime
import itertools
import math
import typing

import pytest
import shapely

import peri_scribe.areas
import peri_scribe.fires.grouping
import peri_scribe.fires.index
import peri_scribe.geo.measurements
import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.history_index
import peri_scribe.presentation.index
import peri_scribe.presentation.selection
import tests.formal.helpers.grouping
import tests.formal.helpers.oracle
import tests.formal.helpers.sparse_evidence
import tests.helpers.factories.geography
from measurement_units import units


if typing.TYPE_CHECKING:
    import geopandas


VERTICES = 3


@dataclasses.dataclass(frozen=True, kw_only=True)
class Row:
    """Every observation remains attributable to one original grouping record."""

    vertex: int
    time: int
    serial: int
    eligible: bool
    area: int

    def text(self) -> str:
        """Encode raw evidence fields for the Lean composition reference.

        Returns:
            One observation vector without any policy evaluation.
        """
        return (
            f"{self.vertex},{self.time},{self.serial},{int(self.eligible)},{self.area}"
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Case:
    """Alias connectivity and spatial names can produce interleaved histories."""

    records: tuple[peri_scribe.models.FireRecord, ...]
    rows: tuple[Row, ...]

    def command(self, representative: int) -> str:
        """Use the independently declared graph relation with original observation rows.

        Args:
            representative: A source record whose component is being selected.

        Returns:
            A request to the grouping and output definitions proved in Lean.
        """
        graph = tests.formal.helpers.grouping.command(list(self.records)).split()[2:]
        return f"compose {representative} | {' '.join(graph)} | " + " ".join(
            row.text() for row in self.rows
        )


def cases() -> tuple[Case, ...]:
    """Cross alias connectivity, distant same names, missing shapes, and corrections.

    Returns:
        All three-vertex identifier graphs and additional spatial grouping chains.
    """
    records = []
    possible = tuple(itertools.combinations(range(VERTICES), 2))
    for mask in range(1 << len(possible)):
        edges = tuple(edge for bit, edge in enumerate(possible) if mask & (1 << bit))
        records.append(
            tuple(
                peri_scribe.models.FireRecord(
                    name=f"Fire {vertex}",
                    identifiers=frozenset({
                        f"own-{vertex}",
                        *(f"edge-{a}-{b}" for a, b in edges if vertex in {a, b}),
                    }),
                    status=peri_scribe.models.FireStatus.ACTIVE,
                )
                for vertex in range(VERTICES)
            ),
        )
    records.extend(
        tuple(
            peri_scribe.models.FireRecord(
                name="Canyon",
                names=frozenset({"canyon"}),
                identifiers=frozenset({f"own-{vertex}"}),
                status=peri_scribe.models.FireStatus.ACTIVE,
                geometry=shapely.Point(longitude, 40),
            )
            for vertex, longitude in enumerate(locations)
        )
        for locations in ((0, 0.04, 0.08), (0, 0.04, 1), (0, 1, 2))
    )
    return tuple(
        Case(
            records=grouping,
            rows=tuple(
                sorted(
                    (
                        Row(
                            vertex=serial % VERTICES,
                            time=serial + 1 if forward else 6 - serial,
                            serial=serial,
                            eligible=bool(mask & (1 << serial)),
                            area=(24, 26, 50, 1, 10, 25)[serial]
                            if mask & (1 << serial)
                            else 0,
                        )
                        for serial in range(6)
                    ),
                    key=lambda row: row.time,
                ),
            ),
        )
        for grouping, mask, forward in itertools.product(
            records,
            (0, 1, 21, 63),
            (False, True),
        )
    )


def frame(case: Case) -> geopandas.GeoDataFrame:
    """Real stored measurements isolate ownership and policy from geodesic rounding.

    Args:
        case: Original records and their chronological observations.

    Returns:
        A complete perimeter history with independently tagged provenance.
    """
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [f"own-{row.vertex}" for row in case.rows],
            "fire_name": [case.records[row.vertex].name for row in case.rows],
            "observation_time": [
                tests.formal.helpers.sparse_evidence.ORIGIN
                + datetime.timedelta(seconds=row.time)
                for row in case.rows
            ],
            "source_subsource": ["FIRIS"] * len(case.rows),
            "source_file": [str(row.serial) for row in case.rows],
            "source_objectid": [row.serial for row in case.rows],
            "area_acres": [None] * len(case.rows),
            peri_scribe.geo.measurements.AREA_COLUMN: [
                (row.area * units.acres).m_as("meters ** 2") for row in case.rows
            ],
            peri_scribe.perimeters.progression.SEQUENCE_COLUMN: [
                str(row.serial) for row in case.rows
            ],
        },
        [
            shapely.box(-120.01, 40, -120, 40.01) if row.eligible else shapely.Polygon()
            for row in case.rows
        ],
    )


def check_cases() -> None:
    """Batch grouping queries while keeping each presentation scenario independent."""
    scenarios = cases()
    grouped = [
        peri_scribe.fires.grouping.group_fire_record_indices(list(case.records))
        for case in scenarios
    ]
    expected = tests.formal.helpers.oracle.evaluate_batches(
        [
            [case.command(min(group)) for group in groups]
            for case, groups in zip(scenarios, grouped, strict=True)
        ],
        executable="oraclePresentation",
    )
    for case, groups, outcomes in zip(scenarios, grouped, expected, strict=True):
        check(case, groups, outcomes)


def check(
    case: Case,
    groups: list[list[int]],
    expected: list[tuple[int, ...]],
) -> None:
    """Connect component proofs to actual aliases, frames, histories, and both outputs.

    Args:
        case: One complete grouping-to-presentation input scenario.
        groups: Actual source grouping for this case.
        expected: Checked membership and output decisions for every group.
    """
    fires = [
        peri_scribe.fires.grouping.most_common_fire([
            case.records[index] for index in group
        ])
        for group in groups
    ]
    index = peri_scribe.models.FireIndex(
        version="formal",
        fires=[
            peri_scribe.models.FireIndexEntry.model_validate({
                **peri_scribe.fires.index.fire_document(fire),
                "paths": [],
            })
            for fire in fires
        ],
    )
    perimeters = frame(case)
    empty = perimeters.iloc[0:0]
    histories = peri_scribe.presentation.index.prepare_histories(
        index,
        perimeters,
        empty,
    )
    prepared = peri_scribe.presentation.fire_data.prepare_fire_data(
        index,
        perimeters,
        empty,
        empty,
        histories=histories,
    )
    eligible_identifiers = []
    all_members = []
    for fire, output, result in zip(fires, prepared, expected, strict=True):
        all_members.extend(check_prepared(perimeters, output, result))
        if result[-3]:
            eligible_identifiers.append(fire.aliases)
    assert sorted(all_members) == list(range(len(case.rows)))
    check_outputs(index, perimeters, histories, frozenset(eligible_identifiers))


def check_prepared(
    perimeters: geopandas.GeoDataFrame,
    output: peri_scribe.presentation.fire_data.PreparedFire,
    result: tuple[int, ...],
) -> tuple[int, ...]:
    """Compare exact source ownership, drawable chronology, and selected acreage.

    Args:
        perimeters: The input history with original source serials.
        output: Facts prepared by the actual shared presentation path.
        result: Lean's expected membership, timeline, and acreage.

    Returns:
        Actual source serials used for this output fire.
    """
    count = result[0]
    drawn_count = result[count + 1]
    assert len(result) == count + 2 * drawn_count + 5
    actual_members = tuple(
        int(perimeters.iloc[position]["source_file"])
        for position in output.perimeter_positions
    )
    assert actual_members == result[1 : count + 1]
    assert len(output.summary.perimeters) == drawn_count
    for item, serial, time in zip(
        output.summary.perimeters,
        result[count + 2 : count + 2 + drawn_count],
        result[count + 2 + drawn_count : count + 2 + 2 * drawn_count],
        strict=True,
    ):
        assert item.sequence_digest == str(serial)
        assert item.observation_time is not None
        assert (
            item.observation_time - tests.formal.helpers.sparse_evidence.ORIGIN
        ).total_seconds() == time
    assert output.history is not None
    for actual, value in zip(
        (output.history.latest_area, output.history.historical_area),
        result[-2:],
        strict=True,
    ):
        if value == tests.formal.helpers.sparse_evidence.MISSING:
            assert actual is None
        else:
            assert actual is not None
            assert math.isclose(actual.m_as("acres"), value, abs_tol=1e-9)
    return actual_members


def check_outputs(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    histories: dict[
        peri_scribe.presentation.selection.AreaKey,
        peri_scribe.areas.PreparedHistory,
    ],
    eligible_identifiers: frozenset[frozenset[str]],
) -> None:
    """Both output adapters must retain the same historically qualified identities.

    Args:
        index: The grouped canonical identities and aliases.
        perimeters: The complete frame used to prepare shared histories.
        histories: Actual shared source and area evidence for each canonical fire.
        eligible_identifiers: The exact eligible groups returned by Lean.
    """
    empty = perimeters.iloc[0:0]
    qualified_index = peri_scribe.presentation.index.area_qualified_index(
        index,
        perimeters,
        empty,
        histories=histories,
    )
    summaries = peri_scribe.presentation.fire_data.fire_summaries(
        qualified_index,
        perimeters,
        empty,
        empty,
        histories=histories,
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        for name in ("fire_plots", "fire_plots_from_history"):
            monkeypatch.setattr(
                peri_scribe.kml.plot_data,
                name,
                lambda *_args, **_kwargs: (),
            )
        monkeypatch.setattr(
            peri_scribe.kml.plot_rendering,
            "plot_image_bundles",
            lambda bundles, **_kwargs: tuple(() for _ in bundles),
        )
        geometries = peri_scribe.kml.fire_data.fire_geometries(
            qualified_index,
            perimeters,
            empty,
            empty,
            histories=histories,
        )
    assert {fire.identifiers for fire in summaries} == eligible_identifiers
    assert {fire.identifiers for fire in geometries} == eligible_identifiers


def check_keyed_selection() -> None:
    """Keep canonical tagged area ownership distinct from descriptive name fallback."""
    rows = tuple(itertools.product((None, 0, 1, 2), (0, 1, 2)))
    frame = tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [
                None if identifier is None else str(identifier)
                for identifier, _ in rows
            ],
            "fire_name": [str(name) for _, name in rows],
        },
        [shapely.Point(0, 0)] * len(rows),
    )
    vectors = " ".join(
        f"{'n' if identifier is None else identifier},{name},{serial}"
        for serial, (identifier, name) in enumerate(rows)
    )
    assignments = tuple(itertools.product(range(3), repeat=3))
    outcomes = tests.formal.helpers.oracle.evaluate_batches(
        [
            [
                f"keyed {kind} {owner} | {' '.join(map(str, aliases))} | {vectors}"
                for kind, owner in itertools.product(("id", "name"), range(3))
            ]
            for aliases in assignments
        ],
        executable="oraclePresentation",
    )
    for aliases, answers in zip(assignments, outcomes, strict=True):
        grouped = peri_scribe.presentation.selection.area_positions(
            frame,
            {str(index): str(owner) for index, owner in enumerate(aliases)},
        )
        for (kind, owner), outcome in zip(
            itertools.product(("id", "name"), range(3)),
            answers,
            strict=True,
        ):
            assert tuple(grouped.get((kind, str(owner)), ())) == outcome
    indexed = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
    selections = tuple(
        (tuple(index for index in range(3) if mask & (1 << index)), name)
        for mask, name in itertools.product(range(8), range(3))
    )
    expected = tests.formal.helpers.oracle.evaluate(
        [
            f"matched {name} | {' '.join(map(str, identifiers))} | {vectors}"
            for identifiers, name in selections
        ],
        executable="oraclePresentation",
    )
    for (identifiers, name), answer in zip(selections, expected, strict=True):
        assert (
            indexed.positions_for(frozenset(map(str, identifiers)), str(name)) == answer
        )
