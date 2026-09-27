"""Connect checked publication ownership to real qualified indexes and output facts."""

from __future__ import annotations

import collections
import dataclasses
import datetime
import itertools
import json
import pathlib
import typing

import shapely

import peri_scribe.geo.measurements
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.index
import peri_scribe.publication
import tests.formal.helpers.publication_baseline
import tests.helpers.factories.geography
from measurement_units import units


if typing.TYPE_CHECKING:
    import geopandas


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scenario:
    """Declare qualified entries and their source witnesses before execution."""

    case: tests.formal.helpers.publication_baseline.Case
    candidates: tuple[tests.formal.helpers.publication_baseline.Entry, ...]
    acres: tuple[int, ...]
    members: tuple[tuple[int, ...], ...]


def cases() -> tuple[Scenario, ...]:
    """Exercise provenance at the boundary between area policy and baseline ownership.

    Returns:
        Qualifying, excluded, anonymous, enriched, corrected, and grouped histories.
    """
    source = tests.formal.helpers.publication_baseline.Source
    row = tests.formal.helpers.publication_baseline.Row
    entry = tests.formal.helpers.publication_baseline.Entry
    case = tests.formal.helpers.publication_baseline.Case
    identified = entry(identifier=0, name=0)
    other = entry(identifier=1, name=1)
    anonymous = entry(identifier=None, name=0)
    histories = (
        Scenario(
            case=case(
                sources=(source(file=0, object_id=0, identity=0, aliases=(0,)),),
                rows=(row(identifier=0, name=0, file=0, object_id=0),),
                entries=(identified,),
            ),
            candidates=(identified,),
            acres=(100,),
            members=((0,),),
        ),
        Scenario(
            case=case(
                sources=(
                    source(file=0, object_id=0, identity=0, aliases=(0,)),
                    source(file=1, object_id=0, identity=1, aliases=(1,)),
                ),
                rows=(
                    row(identifier=0, name=0, file=0, object_id=0),
                    row(identifier=1, name=1, file=1, object_id=0),
                ),
                entries=(identified,),
            ),
            candidates=(identified, other),
            acres=(100, 1),
            members=((0,),),
        ),
        Scenario(
            case=case(
                sources=(source(file=0, object_id=0, identity=0, aliases=(2,)),),
                rows=(row(identifier=1, name=1, file=0, object_id=0, aliases=(3,)),),
                entries=(entry(identifier=0, name=0, aliases=(1,)),),
            ),
            candidates=(entry(identifier=0, name=0, aliases=(1,)),),
            acres=(100,),
            members=((0,),),
        ),
        Scenario(
            case=case(
                sources=(source(file=0, object_id=None, identity=0),),
                rows=(row(identifier=None, name=0, file=0, object_id=None),),
                entries=(anonymous,),
            ),
            candidates=(anonymous,),
            acres=(100,),
            members=((0,),),
        ),
        Scenario(
            case=case(
                sources=(source(file=0, object_id=0, identity=0),),
                rows=(row(identifier=None, name=0, file=0, object_id=0),),
                entries=(),
            ),
            candidates=(identified,),
            acres=(100,),
            members=(),
        ),
        Scenario(
            case=case(
                sources=(source(file=0, object_id=0, identity=0, aliases=(0,)),),
                rows=(row(identifier=0, name=0, file=0, object_id=0),),
                entries=(),
            ),
            candidates=(identified,),
            acres=(1,),
            members=(),
        ),
        Scenario(
            case=case(
                sources=(
                    source(file=0, object_id=0, identity=0, aliases=(0,)),
                    source(file=1, object_id=0, identity=1, aliases=(1,)),
                ),
                rows=(
                    row(identifier=0, name=0, file=0, object_id=0),
                    row(identifier=0, name=1, file=1, object_id=0, aliases=(2,)),
                ),
                entries=(identified,),
            ),
            candidates=(identified,),
            acres=(100, 1),
            members=((0, 1),),
        ),
        Scenario(
            case=case(
                sources=(
                    source(file=0, object_id=0, identity=0, aliases=(0,)),
                    source(file=1, object_id=0, identity=1, aliases=(1,)),
                ),
                rows=(
                    row(identifier=0, name=0, file=0, object_id=0),
                    row(identifier=1, name=1, file=1, object_id=0),
                ),
                entries=(entry(identifier=0, name=0, aliases=(1,)),),
            ),
            candidates=(entry(identifier=0, name=0, aliases=(1,)),),
            acres=(100, 1),
            members=((0, 1),),
        ),
        Scenario(
            case=case(
                sources=(
                    source(file=0, object_id=0, identity=0),
                    source(file=1, object_id=0, identity=1, aliases=(1,)),
                ),
                rows=(
                    row(identifier=None, name=0, file=0, object_id=0),
                    row(identifier=1, name=0, file=1, object_id=0),
                ),
                entries=(anonymous,),
            ),
            candidates=(anonymous, entry(identifier=1, name=0)),
            acres=(100, 1),
            members=((0,),),
        ),
    )
    return tuple(
        dataclasses.replace(
            scenario,
            case=dataclasses.replace(
                scenario.case,
                rows=tuple(reversed(scenario.case.rows))
                if rows
                else scenario.case.rows,
            ),
            candidates=tuple(reversed(scenario.candidates))
            if entries
            else scenario.candidates,
            acres=tuple(reversed(scenario.acres)) if rows else scenario.acres,
            members=tuple(
                tuple(len(scenario.case.rows) - 1 - position for position in members)
                if rows
                else members
                for members in scenario.members
            ),
        )
        for scenario in histories
        for rows, entries in itertools.product(
            (False, True) if len(scenario.case.rows) > 1 else (False,),
            (False, True) if len(scenario.candidates) > 1 else (False,),
        )
    )


def frame(scenario: Scenario) -> geopandas.GeoDataFrame:
    """Give actual history preparation independent source and displayed measurements.

    Args:
        scenario: Raw ownership inputs with known above/below-threshold areas.

    Returns:
        A complete, normalized derived perimeter history ready for production adapters.
    """
    rows = scenario.case.rows
    return tests.helpers.factories.geography.geo_frame(
        {
            "fire_identifier": [
                None if row.identifier is None else f"i{row.identifier}" for row in rows
            ],
            "fire_name": [f"Fire {row.name}" for row in rows],
            "fire_aliases": [
                ",".join(f"i{alias}" for alias in row.aliases) for row in rows
            ],
            "source_file": [f"{row.file}.gpkg" for row in rows],
            "source_objectid": [row.object_id for row in rows],
            "source_subsource": ["FIRIS"] * len(rows),
            "observation_time": [
                tests.formal.helpers.publication_baseline.ORIGIN
                + datetime.timedelta(hours=position)
                for position in range(len(rows))
            ],
            "area_acres": [None] * len(rows),
            peri_scribe.geo.measurements.AREA_COLUMN: [
                (area * units.acres).m_as("meters ** 2") for area in scenario.acres
            ],
            peri_scribe.perimeters.progression.SEQUENCE_COLUMN: [
                str(position) for position in range(len(rows))
            ],
        },
        [shapely.box(-120.01, 40, -120, 40.01)] * len(rows),
    )


def check_summaries(
    scenario: Scenario,
    summaries: list[peri_scribe.presentation.fire_data.FireSummary],
) -> None:
    """Require every output fact to retain exactly its declared source witnesses.

    Args:
        scenario: The independently declared qualifying groups and selected rows.
        summaries: Real summaries from the shared output adapter.
    """
    actual = {
        (
            peri_scribe.models.canonical_fire_identifier(fire.identifiers),
            fire.name,
        ): fire
        for fire in summaries
    }
    assert len(actual) == len(scenario.case.entries) == len(summaries)
    for entry, members in zip(scenario.case.entries, scenario.members, strict=True):
        key = None if entry.identifier is None else f"i{entry.identifier}"
        fire = actual[key, f"Fire {entry.name}"]
        assert fire.identifiers == frozenset(
            f"i{value}"
            for value in (
                *(() if entry.identifier is None else (entry.identifier,)),
                *entry.aliases,
            )
        )
        references = collections.Counter(
            frozenset()
            if scenario.case.rows[position].object_id is None
            else frozenset({
                (
                    f"{scenario.case.rows[position].file}.gpkg#"
                    f"{scenario.case.rows[position].object_id}"
                ),
            })
            for position in members
        )
        assert (
            collections.Counter(
                perimeter.source_references for perimeter in fire.perimeters
            )
            == references
        )


def check(
    scenario: Scenario,
    expected: tuple[int, ...],
    directory: pathlib.Path,
) -> None:
    """Compose qualified output facts, the checked baseline, and checkpoint readback.

    Args:
        scenario: An independently declared publication and qualification boundary case.
        expected: The compiled Lean baseline result using the expected qualified index.
        directory: Private storage for an output identity fixture and its checkpoint.
    """
    perimeters = frame(scenario)
    empty = perimeters.iloc[0:0]
    candidates = dataclasses.replace(scenario.case, entries=scenario.candidates).index()
    histories = peri_scribe.presentation.index.prepare_histories(
        candidates,
        perimeters,
        empty,
    )
    qualified = peri_scribe.presentation.index.area_qualified_index(
        candidates,
        perimeters,
        empty,
        histories=histories,
    )
    assert {entry.model_dump_json() for entry in qualified.fires} == {
        entry.model_dump_json() for entry in scenario.case.index().fires
    }
    summaries = peri_scribe.presentation.fire_data.fire_summaries(
        qualified,
        perimeters,
        empty,
        empty,
        histories=histories,
    )
    check_summaries(scenario, summaries)
    collection = scenario.case.collection()
    actual = peri_scribe.publication.published_fires(collection, perimeters, qualified)
    assert tests.formal.helpers.publication_baseline.encode_result(actual) == expected
    sources = {source.identity: source.production() for source in scenario.case.sources}
    for fire in actual.values():
        if fire.mapping is not None:
            identity = int(fire.mapping.name.removeprefix("Source "))
            assert fire.mapping == sources[identity]
    directory.mkdir()
    output = directory / "completed-output.json"
    output.write_text(json.dumps([fire.name for fire in summaries]))
    peri_scribe.publication.commit(directory, output, collection, actual)
    saved = peri_scribe.publication.read_publication(directory, output)
    assert saved is not None
    assert saved.fires == actual
    assert (
        tests.formal.helpers.publication_baseline.encode_result(saved.fires) == expected
    )
    assert saved.output == peri_scribe.publication.file_stamp(output)
