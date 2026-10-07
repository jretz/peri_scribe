"""Connect component ownership to source grouping, stored geography, and publication."""

from __future__ import annotations

import collections
import dataclasses
import datetime
import hashlib
import itertools
import json
import pathlib

import geopandas
import pytest
import shapely

import peri_scribe.fire_updates
import peri_scribe.fires.differential
import peri_scribe.fires.identity
import peri_scribe.fires.sources
import peri_scribe.kml.fire_data
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.history_index
import peri_scribe.presentation.index
import peri_scribe.presentation.views
import peri_scribe.report.gathering
import spatial_data.layers
import tests.formal.helpers.grouping
import tests.formal.helpers.identity_transfer
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.component_identity


type Read = peri_scribe.fires.sources.ReadFireSources
type Anchor = tuple[str, int, str, str, int]
VERTICES = 3
PREFIXES = ("name:", "component:", "id:")


def reordered(read: Read, order: tuple[int, ...]) -> Read:
    """Move complete source occurrences together without changing their contents.

    Args:
        read: The immutable source catalogue.
        order: A permutation of row positions.

    Returns:
        The same observations and source paths in the supplied order.
    """
    return dataclasses.replace(
        read,
        rows=tuple(read.rows[index] for index in order),
        paths=tuple(read.paths[index] for index in order),
    )


def cases() -> tuple[Read, ...]:
    """Cross every three-row identifier graph with anonymous spatial ownership.

    Returns:
        Permuted distant/nearby records with present and missing source object IDs.
    """
    base = tests.helpers.factories.peri_scribe.component_identity.sources(
        pathlib.Path("sources"),
    )
    possible = tuple(itertools.combinations(range(VERTICES), 2))
    result = []
    for mask, near, missing in itertools.product(
        range(8),
        (False, True),
        (False, True),
    ):
        rows = tuple(
            dataclasses.replace(
                base.rows[0],
                object_id=None if missing else vertex,
                record=dataclasses.replace(
                    base.rows[0].record,
                    identifiers=frozenset(
                        f"edge-{left}-{right}"
                        for bit, (left, right) in enumerate(possible)
                        if mask & (1 << bit) and vertex in {left, right}
                    ),
                    geometry=shapely.Point(-120 + vertex * (0.04 if near else 2), 40),
                ),
                attributes={"vertex": vertex},
            )
            for vertex in range(VERTICES)
        )
        read = dataclasses.replace(base, rows=rows, paths=(base.paths[0],) * VERTICES)
        result.extend(
            reordered(read, order) for order in itertools.permutations(range(3))
        )
    for geometry in (None, shapely.Point()):
        row = dataclasses.replace(
            base.rows[0],
            object_id=None,
            record=dataclasses.replace(base.rows[0].record, geometry=geometry),
        )
        result.append(dataclasses.replace(base, rows=(row, row)))
    return tuple(result)


def raw_anchors(read: Read) -> tuple[Anchor, ...]:
    """Frame declared source fields independently of the application's anchor helpers.

    Args:
        read: Raw typed records and their immutable snapshot paths.

    Returns:
        Structured ordered occurrences supplied to the minimum-selection oracle.
    """
    counts: collections.Counter[tuple[str, int, str, str]] = collections.Counter()
    result = []
    for row, path in zip(read.rows, read.paths, strict=True):
        record = row.record
        payload: object = ["object", row.object_id]
        if row.object_id is None:
            payload = [
                "record",
                record.name,
                record.status.value,
                sorted(record.identifiers),
                sorted(record.names),
                None if record.geometry is None else record.geometry.wkb_hex,
                None if record.observed_at is None else record.observed_at.isoformat(),
                record.mission,
                record.point_of_origin_state,
                record.point_of_origin_fips,
                row.attributes,
            ]
        token = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        serial = int(path.name.split(",", 1)[0])
        key = row.source_name, serial, path.name, token
        result.append((*key, counts[key]))
        counts[key] += 1
    return tuple(result)


def digest(anchor: Anchor) -> str:
    """Represent oracle-selected structured tokens in the real opaque-key format.

    Args:
        anchor: The structured occurrence selected by the executable definition.

    Returns:
        The same SHA-256 representation used at the application boundary.
    """
    return hashlib.sha256(json.dumps(anchor).encode()).hexdigest()


def check_grouping() -> int:
    """Check actual grouping, anchor selection, and complete internal alias routing.

    Returns:
        Number of source catalogues compared with both executable Lean definitions.
    """
    catalogues = cases()
    labels = tests.formal.helpers.oracle.evaluate(
        [
            tests.formal.helpers.grouping.command([row.record for row in read.rows])
            for read in catalogues
        ],
        executable="oracleDomain",
    )
    grouped = tuple(map(peri_scribe.fires.sources.group_fire_sources, catalogues))
    commands = []
    for read, groups in zip(catalogues, grouped, strict=True):
        anchors = raw_anchors(read)
        ordered = sorted(anchors)
        for group in groups.groups:
            ranks = " ".join(str(ordered.index(anchors[index])) for index in group)
            commands.extend((f"anchor|{ranks}", f"components|{ranks}"))
    answers = iter(
        tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleComponentIdentity",
        ),
    )
    for read, expected, groups in zip(catalogues, labels, grouped, strict=True):
        ordered = sorted(raw_anchors(read))
        members = [
            tuple(index for index, owner in enumerate(expected) if owner == value)
            for value in sorted(set(expected))
        ]
        assert {frozenset(group) for group in groups.groups} == {
            frozenset(group) for group in members
        }
        assert len({fire.component_id for fire in groups.fires}) == len(groups.fires)
        for fire, group in zip(
            groups.fires,
            groups.groups,
            strict=True,
        ):
            (minimum,) = next(answers)
            assert fire.component_id == digest(ordered[minimum])
            alias_pairs = next(answers)
            assert set(alias_pairs[::2]) == {1}
            assert fire.component_aliases == frozenset(
                digest(ordered[rank]) for rank in alias_pairs[1::2]
            )
            assert fire.aliases == frozenset().union(
                *(read.rows[index].record.identifiers for index in group),
            )
    return len(catalogues)


def prefix_tokens(value: str) -> tuple[int, ...]:
    """Tokenize only the reserved namespace boundaries; ordinary suffixes stay opaque.

    Args:
        value: An arbitrary key payload or serialized scoring identity.

    Returns:
        Reserved prefix symbols followed by an opaque ordinary suffix symbol.
    """
    for token, prefix in enumerate(PREFIXES):
        if value.startswith(prefix):
            return (token, *prefix_tokens(value[len(prefix) :]))
    return (3,) if value else ()


def check_storage_keys() -> int:
    """Exercise namespace text, nested escapes, and exact tagged selection.

    Returns:
        Number of real scoring keys compared with Lean's reversible encoding.
    """
    payloads = ("", "Canyon", "name:", "component:", "id:", "雪:fire")
    texts = tuple(
        "".join(prefixes) + suffix
        for count in range(3)
        for prefixes in itertools.product(PREFIXES, repeat=count)
        for suffix in payloads
    )
    requests = []
    observed = []
    unique: dict[str, tuple[str, str]] = {}
    for kind, text in itertools.product(("id", "name", "component"), texts):
        key = peri_scribe.fires.identity.identity_key(
            text if kind == "name" else "Canyon",
            text if kind == "id" else None,
            text if kind == "component" else None,
        )
        assert key not in unique or unique[key] == (kind, text)
        unique[key] = kind, text
        requests.append(f"storage|{kind}|" + " ".join(map(str, prefix_tokens(text))))
        observed.append(prefix_tokens(key))
    assert (
        tests.formal.helpers.oracle.evaluate(
            requests,
            executable="oracleComponentIdentity",
        )
        == observed
    )
    return len(requests)


def check_tagged_keys() -> int:
    """The application uses the proved external/component/name priority and aliases.

    Returns:
        Number of present/missing identity combinations with colliding display text.
    """
    cases = tuple(itertools.product((None, 7), (None, 7), (7, 8)))
    commands = [
        f"{operation}|{'n' if identifier is None else identifier}|"
        f"{'n' if component is None else component}|{name}"
        for identifier, component, name in cases
        for operation in ("key", "aliases")
    ]
    answers = iter(
        tests.formal.helpers.oracle.evaluate(
            commands,
            executable="oracleComponentIdentity",
        ),
    )
    kinds = {"id": 0, "component": 1, "name": 2}
    for identifier, component, name in cases:
        fire = peri_scribe.presentation.fire_data.FireSummary(
            name=str(name),
            status=peri_scribe.models.FireStatus.ACTIVE,
            identifiers=frozenset()
            if identifier is None
            else frozenset({str(identifier)}),
            component_id=None if component is None else str(component),
            point=None,
            perimeters=(),
        )
        key = peri_scribe.report.gathering.fire_identity(fire)
        assert (kinds[key[0]], int(key[1])) == next(answers)
        aliases = [
            json.loads(alias) for alias in peri_scribe.fire_updates.identity_keys(fire)
        ]
        assert tuple(
            value for kind, text in aliases for value in (kinds[kind], int(text))
        ) == next(answers)
    return len(cases)


def stored_summaries(
    read: Read,
    directory: pathlib.Path,
) -> list[peri_scribe.presentation.fire_data.FireSummary]:
    """Carry source groups through real GeoPackages, qualification, drawing, and scores.

    Args:
        read: The source catalogue for this publication round.
        directory: An isolated scratch directory for complete history artifacts.

    Returns:
        Type 1 summaries admitted by the real report selector, with exact ownership.
    """
    factory = tests.helpers.factories.peri_scribe.component_identity
    index, full, points = factory.histories(read, pathlib.Path("sources"))
    differential = peri_scribe.fires.differential.differential_perimeter_dataframe(full)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "history.gpkg"
    spatial_data.layers.write_geopackage(
        path,
        [
            spatial_data.layers.LayerData(name="full", dataframe=full),
            spatial_data.layers.LayerData(name="growth", dataframe=differential),
        ],
    )
    full = geopandas.read_file(path, layer="full")
    differential = geopandas.read_file(path, layer="growth")
    prepared = peri_scribe.presentation.index.prepare_histories(index, full, points)
    qualified = peri_scribe.presentation.index.area_qualified_index(
        index,
        full,
        points,
        histories=prepared,
    )
    assert len(qualified.fires) == len(index.fires)
    summaries = peri_scribe.presentation.fire_data.fire_summaries(
        qualified,
        full,
        points,
        differential,
        histories=prepared,
    )
    assert len(summaries) == len(index.fires)
    components = sorted(
        entry.component_id for entry in index.fires if entry.component_id is not None
    )
    assert len(components) == len(index.fires)
    row_owners = [
        components.index(component) for component in full["fire_component_id"]
    ]
    selected = tests.formal.helpers.oracle.evaluate(
        [
            f"select|{components.index(str(fire.component_id))}|"
            + " ".join(map(str, row_owners))
            for fire in summaries
        ],
        executable="oracleComponentIdentity",
    )
    row_index = peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(full)
    for fire, positions in zip(summaries, selected, strict=True):
        assert (
            row_index.positions_for(fire.identifiers, fire.name, fire.component_id)
            == positions
        )
        assert len(fire.perimeters) == len(positions)
        assert {item.geometry.wkb for item in fire.perimeters} == {
            full.geometry.iloc[position].wkb for position in positions
        }
        assert fire.description is not None
        assert fire.description.area == fire.perimeters[-1].measured_area
    check_scores(summaries)
    return check_map_output(index, full, points, differential, summaries)


def check_map_output(
    index: peri_scribe.models.FireIndex,
    full: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    differential: geopandas.GeoDataFrame,
    summaries: list[peri_scribe.presentation.fire_data.FireSummary],
) -> list[peri_scribe.presentation.fire_data.FireSummary]:
    """Carry map-adapter identities into the real journal publication checks.

    Args:
        index: The source-derived output identities.
        full: Stored full geography with component attribution.
        points: Stored point evidence.
        differential: Stored visible growth geography.
        summaries: Independently selected report facts checked against Lean.

    Returns:
        Real map geometry objects; plot-image generation alone is replaced.
    """
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
            index,
            full,
            points,
            differential,
        )
    assert len(geometries) == len(summaries)
    for geometry, summary in zip(geometries, summaries, strict=True):
        assert geometry.component_id == summary.component_id
        assert geometry.component_aliases == summary.component_aliases
        assert geometry.identifiers == summary.identifiers
        assert geometry.perimeters == summary.perimeters
    return [dataclasses.replace(fire, type_one=True) for fire in geometries]


def check_scores(
    summaries: list[peri_scribe.presentation.fire_data.FireSummary],
) -> None:
    """Check exact component selection through scores and report de-duplication.

    Args:
        summaries: Source-derived, qualified anonymous or identified fires.
    """
    scores = peri_scribe.models.FireScores(
        version="formal",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name=fire.name,
                identifier=peri_scribe.models.canonical_fire_identifier(
                    fire.identifiers,
                ),
                component_id=fire.component_id,
                score=position + 1,
                explanation=f"component-{fire.component_id}",
            )
            for position, fire in enumerate(summaries)
        ],
    )
    matched = peri_scribe.presentation.views.matched_fire_scores(summaries, scores)
    assert len(matched) == len(summaries)
    for fire, score in matched:
        assert score.component_id == fire.component_id
    score_maps = peri_scribe.presentation.views.score_maps(scores)
    entries = peri_scribe.report.gathering.report_entries(
        summaries,
        *score_maps,
        datetime.datetime(2026, 9, 26, tzinfo=datetime.UTC),
    )
    assert len(peri_scribe.report.gathering.report_details(entries, entries)) == len(
        summaries,
    )
    assert len({
        peri_scribe.report.gathering.fire_identity(fire) for fire in summaries
    }) == len(summaries)


def publication_catalogues() -> tuple[Read, ...]:
    """Retained anchors survive enrichment, while corrected grouping can merge or split.

    Returns:
        Complete source inputs before and after identifier corrections and reversals.
    """
    base = tests.helpers.factories.peri_scribe.component_identity.sources(
        pathlib.Path("sources"),
    )
    additions = tuple(
        dataclasses.replace(
            row,
            record=dataclasses.replace(
                row.record,
                identifiers=frozenset({f"2026-CA-00000{index}"}),
                observed_at=row.record.observed_at + datetime.timedelta(hours=index)
                if row.record.observed_at is not None
                else None,
            ),
        )
        for index, row in enumerate(base.rows, start=1)
    )
    later_paths = tuple(
        path.with_name("000001,lastEdit=1790380800000.gpkg") for path in base.paths
    )
    enriched = dataclasses.replace(
        base,
        rows=(*base.rows, *additions),
        paths=(*base.paths, *later_paths),
    )
    merged = dataclasses.replace(
        enriched,
        rows=(
            *base.rows,
            *(
                dataclasses.replace(
                    row,
                    record=dataclasses.replace(
                        row.record,
                        identifiers=row.record.identifiers | {"merged-alias"},
                    ),
                )
                for row in additions
            ),
        ),
    )
    return base, reordered(base, (1, 0)), enriched, merged, enriched, merged, enriched


def check_publications(directory: pathlib.Path) -> int:
    """The checked transfer oracle sees real source-derived component aliases.

    Args:
        directory: Isolated complete geography, checkpoint, log, and viewer artifacts.

    Returns:
        Number of acknowledged publications and idempotent recomputation checks.
    """
    count = 0
    for reverse in (False, True):
        previous = peri_scribe.fire_updates.State()
        for number, catalogue in enumerate(publication_catalogues()):
            read = (
                reordered(catalogue, tuple(reversed(range(len(catalogue.rows)))))
                if reverse
                else catalogue
            )
            fires = stored_summaries(read, directory / f"geography-{reverse}-{number}")
            previous, _projection = (
                tests.formal.helpers.identity_transfer.publish_round(
                    directory / f"year-{reverse}",
                    fires,
                    previous,
                    number,
                )
            )
            count += 1
    return count
