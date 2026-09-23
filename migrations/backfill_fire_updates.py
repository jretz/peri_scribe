"""Reconstruct fire updates in an isolated year directory from retained evidence.

Run with the project virtual environment and an explicit output directory. Historical
selection uses current rules, retained identities and history, and available external
datasets. The audit records these limits because historical reports were not archived.
"""

from __future__ import annotations

import collections
import compression.zstd
import dataclasses
import datetime
import functools
import hashlib
import json
import pathlib
import tempfile
import time
import unittest.mock

import click
import geopandas
import pandas as pd
import time_machine

import peri_scribe.fire_updates
import peri_scribe.fires.buffering
import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.identity
import peri_scribe.fires.index
import peri_scribe.fires.scores
import peri_scribe.fires.scoring
import peri_scribe.geo.parsing
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.history_index
import peri_scribe.presentation.index
import peri_scribe.presentation.selection
import peri_scribe.publication
import peri_scribe.report.gathering
import peri_scribe.updates
import spatial_data.layers


@dataclasses.dataclass(frozen=True, kw_only=True)
class Build:
    """A successful KMZ uses the sources available when geography started."""

    cutoff: datetime.datetime
    completed: datetime.datetime


def successful_builds(directory: pathlib.Path) -> list[Build]:
    """Retain completed KMZs, including legacy log records without run identifiers.

    Args:
        directory: The diagnostic log directory.

    Returns:
        Distinct successful builds ordered by their completion times.
    """
    paths = {
        path.name.removesuffix(".zst"): path
        for path in directory.glob("????-??.jsonl.zst")
    }
    paths.update({path.name: path for path in directory.glob("????-??.jsonl")})
    starts: dict[str, datetime.datetime] = {}
    builds: dict[datetime.datetime, Build] = {}
    last_geography: datetime.datetime | None = None
    for path in sorted(paths.values()):
        opener = compression.zstd.open if path.suffix == ".zst" else pathlib.Path.open
        with opener(path, "rt") as stream:
            for line in stream:
                entry = json.loads(line)
                when = datetime.datetime.fromisoformat(entry["timestamp"])
                run = entry.get("run_id", "legacy")
                if (
                    entry.get("event") == "Starting phase"
                    and entry.get("phase") == "geography"
                ):
                    starts[run] = when
                if (
                    entry.get("event") == "Finished phase"
                    and entry.get("status") == "completed"
                ):
                    if entry.get("phase") == "geography":
                        last_geography = starts.get(run, when)
                    elif entry.get("phase") == "kmz":
                        builds[when] = Build(
                            cutoff=last_geography or when,
                            completed=when,
                        )
    return sorted(builds.values(), key=lambda build: build.completed)


def available_history(
    frame: geopandas.GeoDataFrame,
    collection: peri_scribe.publication.Collection,
    *,
    perimeters: bool = False,
) -> geopandas.GeoDataFrame:
    """Use original capture evidence to avoid showing maps before their arrival.

    Args:
        frame: One retained history layer.
        collection: Source file and first-shape-capture metadata.
        perimeters: Whether geometry provenance can recover an earlier first capture.

    Returns:
        History with an availability timestamp for each observation.
    """
    mappings: dict[tuple[str, float | None], peri_scribe.publication.Mapping] = {
        (path, mapping.object_id): mapping
        for path, values in collection.mappings.items()
        for mapping in values
    }
    available = []
    for _, row in frame.iterrows():
        path = str(row["source_file"])
        captured = datetime.datetime.fromtimestamp(
            collection.files[path].modified_nanoseconds / 1_000_000_000,
            datetime.UTC,
        )
        if perimeters:
            object_id = peri_scribe.geo.parsing.numeric_value(row["source_objectid"])
            mapping = mappings[path, object_id]
            captured = mapping.captured_at
        observed = row["observation_time"]
        available.append(captured if pd.isna(observed) else max(captured, observed))
    return geopandas.GeoDataFrame(
        frame.assign(available_at=pd.to_datetime(available, utc=True)),
        crs=frame.crs,
    )


def differential_history(
    perimeters: geopandas.GeoDataFrame,
    cache: dict[tuple[int, ...], geopandas.GeoDataFrame],
) -> geopandas.GeoDataFrame:
    """Reuse only histories with the exact same retained perimeter rows.

    Args:
        perimeters: The full perimeters available for this build.
        cache: Previously computed growth histories keyed by source row positions.

    Returns:
        Growth rings corrected using only the mapping available at this build.
    """
    histories = []
    for _, group in perimeters.groupby(
        peri_scribe.fires.identity.group_keys(perimeters),
    ):
        key = tuple(group.index)
        if key not in cache:
            cache[key] = (
                peri_scribe.fires.differential.differential_perimeter_dataframe(
                    geopandas.GeoDataFrame(group, crs=perimeters.crs),
                )
            )
        histories.append(cache[key])
    return geopandas.GeoDataFrame(
        pd.concat(histories, ignore_index=True),
        crs=perimeters.crs,
    )


def historical_scores(
    year: pathlib.Path,
    fires: list[peri_scribe.presentation.fire_data.FireSummary],
    differential: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
    signal_cache: dict[bytes, tuple[int, bool]],
) -> peri_scribe.models.FireScores:
    """Recompute score tiers while retaining spatial queries for unchanged shapes.

    Args:
        year: The copied year directory containing available external datasets.
        fires: Qualified historical fire summaries.
        differential: Growth history reconstructed without future perimeters.
        points: Incident location observations available at the build.
        signal_cache: Building and evacuation results keyed by geometry bytes.

    Returns:
        Scores using the current scoring rules and available external datasets.
    """
    geometries = [
        fire.perimeters[-1].geometry if fire.perimeters else fire.point
        for fire in fires
    ]
    missing = {
        geometry.wkb: geometry
        for geometry in geometries
        if geometry is not None and geometry.wkb not in signal_cache
    }
    if missing:
        shapes = list(missing.values())
        signals = peri_scribe.fires.scores.external_signals(
            year,
            len(shapes),
            shapes,
            peri_scribe.fires.buffering.buffered_fire_geometries(shapes),
        )
        signal_cache.update({
            shape: (signals.building_counts[index], index in signals.evacuation_indices)
            for index, shape in enumerate(missing)
        })
    metrics, first_mapping = peri_scribe.fires.scores.fire_metrics(
        differential,
        peri_scribe.fires.identity.group_keys(differential),
    )
    point_groups = dict(
        tuple(points.groupby(peri_scribe.fires.identity.group_keys(points))),
    )
    entries = []
    for fire, geometry in zip(fires, geometries, strict=True):
        identifier = peri_scribe.models.canonical_fire_identifier(fire.identifiers)
        key = peri_scribe.fires.identity.identity_key(fire.name, identifier)
        area = None if fire.description is None else fire.description.area
        building_count, evacuation_overlap = (
            (0, False) if geometry is None else signal_cache[geometry.wkb]
        )
        score = peri_scribe.fires.scoring.fire_score_for(
            peri_scribe.fires.scoring.FireRecords(
                name=fire.name,
                identifier=identifier,
                perimeters=differential.iloc[0:0],
                points=point_groups.get(key, points.iloc[0:0]),
            ),
            peri_scribe.fires.scores.perimeter_metrics_for(
                key,
                metrics,
                first_mapping,
                area,
            ),
            building_count=building_count,
            evacuation_overlap=evacuation_overlap,
        )
        entries.append(
            peri_scribe.fires.scoring.score_entry(
                score,
                area=area,
                building_count=building_count,
                evacuation_overlap=evacuation_overlap,
            ),
        )
    return peri_scribe.fires.scoring.fire_scores_document(entries)


def write_backfill(directory: pathlib.Path, records: list[dict[str, object]]) -> None:
    """Merge complete records atomically, preserving existing entries on reruns.

    Args:
        directory: The destination log directory.
        records: Reconstructed records with their original KMZ completion timestamps.
    """
    months: dict[str, list[dict[str, object]]] = collections.defaultdict(list)
    for record in records:
        months[str(record["timestamp"])[:7]].append(record)
    directory.mkdir(parents=True, exist_ok=True)
    compression_month = peri_scribe.logging.compression_month(
        datetime.datetime.now().astimezone(),
    )
    for month, entries in months.items():
        path = directory / f"{month}-fire-updates.jsonl"
        archive = path.with_suffix(".jsonl.zst")
        if archive.exists():
            with compression.zstd.open(archive, "rt") as stream:
                entries.extend(json.loads(line) for line in stream)
        if path.exists():
            entries.extend(json.loads(line) for line in path.read_text().splitlines())
        unique = {json.dumps(entry, sort_keys=True): entry for entry in entries}
        ordered = sorted(
            unique.values(),
            key=lambda entry: (
                str(entry["timestamp"]),
                str(entry["name"]),
                str(entry["identifier"]),
            ),
        )
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            replacement = pathlib.Path(temporary) / path.name
            replacement.write_text(
                "".join(json.dumps(entry, allow_nan=False) + "\n" for entry in ordered),
            )
            if month < compression_month:
                peri_scribe.logging.compress_log(replacement)
                replacement.with_suffix(".jsonl.zst").replace(archive)
                path.unlink(missing_ok=True)
            else:
                replacement.replace(path)
                archive.unlink(missing_ok=True)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Inputs:
    """Retained histories and successful runs are the fixed reconstruction evidence."""

    builds: list[Build]
    perimeters: geopandas.GeoDataFrame
    points: geopandas.GeoDataFrame
    incidents: geopandas.GeoDataFrame
    index: peri_scribe.models.FireIndex


def read_inputs(year: pathlib.Path) -> Inputs:
    """Load copied history and restrict identities to historically qualified fires.

    Args:
        year: The copied year directory.

    Returns:
        Histories annotated with their source availability and the eligible fire index.
    """
    collection = peri_scribe.publication.Collection.model_validate_json(
        (year / "sources" / "publication_cache.json").read_bytes(),
    )
    path = peri_scribe.fires.files.history_geopackage_path(year)
    perimeters = available_history(
        spatial_data.layers.read_layer(path, "perimeter_history"),
        collection,
        perimeters=True,
    )
    points = available_history(
        spatial_data.layers.read_layer(path, "point_history"),
        collection,
    )
    incidents = available_history(
        spatial_data.layers.read_layer(path, "incident_history"),
        collection,
    )
    return Inputs(
        builds=successful_builds(year / "logs"),
        perimeters=perimeters,
        points=points,
        incidents=incidents,
        index=peri_scribe.presentation.index.area_qualified_index(
            peri_scribe.fires.index.load_fire_index(year),
            perimeters,
            points,
            incidents,
        ),
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class CachedSummary:
    """Unchanged source rows imply identical prepared facts across historical builds."""

    signature: tuple[tuple[int, ...], ...]
    summary: peri_scribe.presentation.fire_data.FireSummary | None


def cached_summaries(
    index: peri_scribe.models.FireIndex,
    frames: tuple[geopandas.GeoDataFrame, ...],
    cache: dict[str, CachedSummary],
) -> list[peri_scribe.presentation.fire_data.FireSummary]:
    """Prepare changed fires together while retaining all other historical summaries.

    Args:
        index: The eligible fire identities.
        frames: Full perimeters, points, incidents, and reconstructed differential rows.
        cache: Most recently prepared facts for each fire identity.

    Returns:
        The current qualified summaries for this historical input set.
    """
    indexes = tuple(
        peri_scribe.presentation.history_index.HistoryRowIndex.from_frame(frame)
        for frame in frames
    )
    pending = []
    positions: list[set[int]] = [set() for _frame in frames]
    for entry in index.fires:
        identity = json.dumps((entry.identifier, entry.name))
        selected = tuple(
            frame_index.positions_for(
                peri_scribe.presentation.selection.identifiers(entry),
                entry.name,
            )
            for frame_index in indexes
        )
        signature = tuple(
            tuple(frame.index[list(rows)])
            for frame, rows in zip(frames[:3], selected[:3], strict=True)
        )
        if identity in cache and cache[identity].signature == signature:
            continue
        pending.append((identity, entry, signature))
        for target, rows in zip(positions, selected, strict=True):
            target.update(rows)
    if pending:
        fresh = fresh_summaries(
            index.model_copy(update={"fires": [entry for _, entry, _ in pending]}),
            tuple(
                frame.iloc[sorted(rows)]
                for frame, rows in zip(frames, positions, strict=True)
            ),
        )
        for identity, entry, signature in pending:
            cache[identity] = CachedSummary(
                signature=signature,
                summary=fresh.get(
                    peri_scribe.presentation.selection.fire_area_key(
                        entry.identifier,
                        entry.name,
                    ),
                ),
            )
    return [cached.summary for cached in cache.values() if cached.summary is not None]


def fresh_summaries(
    index: peri_scribe.models.FireIndex,
    frames: tuple[geopandas.GeoDataFrame, ...],
) -> dict[tuple[str, str], peri_scribe.presentation.fire_data.FireSummary]:
    """Use the application's qualification and presentation logic for changed inputs.

    Args:
        index: Identities requiring preparation.
        frames: Full perimeters, points, incidents, and growth rows for those fires.

    Returns:
        Qualified summaries keyed by their tagged report identities.
    """
    full, points, incidents, differential = frames
    histories = peri_scribe.presentation.index.prepare_histories(
        index,
        full,
        points,
        incidents,
    )
    qualified = peri_scribe.presentation.index.area_qualified_index(
        index,
        full,
        points,
        incidents,
        histories=histories,
    )
    return {
        peri_scribe.report.gathering.fire_identity(fire): fire
        for fire in peri_scribe.presentation.fire_data.fire_summaries(
            qualified,
            full,
            points,
            differential,
            incident_rows=incidents,
            histories=histories,
        )
    }


def prepare_build(
    inputs: Inputs,
    build: Build,
    year: pathlib.Path,
    working: pathlib.Path,
    *,
    differential_cache: dict[tuple[int, ...], geopandas.GeoDataFrame],
    signal_cache: dict[bytes, tuple[int, bool]],
    summary_cache: dict[str, CachedSummary],
) -> peri_scribe.fire_updates.PreparedUpdates:
    """Apply report selection using only observations available to this build.

    Args:
        inputs: The fixed reconstruction inputs.
        build: A successful historical build.
        year: The copied external-data directory.
        working: Temporary state for chronological replay.
        differential_cache: Growth histories already reconstructed.
        signal_cache: Spatial queries already evaluated.
        summary_cache: Fire facts already prepared from unchanged source rows.

    Returns:
        Fire records and the baseline acknowledged by this historical build.
    """
    full = inputs.perimeters.loc[inputs.perimeters.available_at <= build.cutoff]
    points = inputs.points.loc[inputs.points.available_at <= build.cutoff]
    incidents = inputs.incidents.loc[inputs.incidents.available_at <= build.cutoff]
    differential = differential_history(full, differential_cache)
    with time_machine.travel(build.completed, tick=False):
        fires = cached_summaries(
            inputs.index,
            (full, points, incidents, differential),
            summary_cache,
        )
        scores = historical_scores(year, fires, differential, points, signal_cache)
        return peri_scribe.fire_updates.prepare_updates(working, fires, scores)


def input_checksums(year: pathlib.Path) -> dict[str, str]:
    """Make the backfill traceable to an immutable copy of its input evidence.

    Args:
        year: The copied input year.

    Returns:
        SHA-256 checksums keyed by year-relative input paths.
    """
    paths = [
        peri_scribe.fires.files.history_geopackage_path(year),
        year / "sources" / "publication_cache.json",
        *sorted((year / "logs").glob("????-??.jsonl*")),
    ]
    checksums = {}
    for path in paths:
        with path.open("rb") as stream:
            checksums[str(path.relative_to(year))] = hashlib.file_digest(
                stream,
                "sha256",
            ).hexdigest()
    return checksums


def backfill_audit(
    year: pathlib.Path,
    inputs: Inputs,
    records: list[dict[str, object]],
    replayed: list[Build],
    state: peri_scribe.fire_updates.State,
    *,
    covered: list[Build],
    limit: int | None,
) -> dict[str, object]:
    """Record reconstruction coverage and the unavailable historical inputs.

    Args:
        year: The copied input year.
        inputs: The reconstruction evidence.
        records: The generated records.
        replayed: Builds requiring a historical selection pass.
        state: The final acknowledged mapping baseline.
        covered: Successful builds covered by the output, including unchanged mapping.
        limit: The requested maximum number of historical selection passes.

    Returns:
        An audit that distinguishes reconstructed selection from archived evidence.
    """
    return {
        "successful_kmz_builds": len(inputs.builds),
        "input_first_completed": inputs.builds[0].completed.isoformat(),
        "input_last_completed": inputs.builds[-1].completed.isoformat(),
        "covered_successful_kmz_builds": len(covered),
        "replayed_builds_with_new_perimeters": len(replayed),
        "first_completed": covered[0].completed.isoformat(),
        "last_completed": covered[-1].completed.isoformat(),
        "last_replayed_completed": (
            replayed[-1].completed.isoformat() if replayed else None
        ),
        "limit": limit,
        "complete": len(covered) == len(inputs.builds),
        "records": len(records),
        "distinct_fires": len({
            peri_scribe.updates.LogEntry.model_validate(entry).identity()
            for entry in records
        }),
        "baseline_fires": len(state.perimeters),
        "selection": (
            "Current report rules applied to retained history available at each build, "
            "with current identities, status, buildings, and evacuation data."
        ),
        "limitations": (
            "Historical reports, scores, evacuation snapshots, superseded geometries, "
            "and earlier attributes on collapsed rows are not archived. This is a "
            "reconstruction, not an exact reproduction of historical reports."
        ),
        "input_sha256": input_checksums(year),
    }


def reconstruct(
    year: pathlib.Path,
    output: pathlib.Path,
    working: pathlib.Path,
    limit: int | None,
) -> None:
    """Backfill only builds evidenced by a successful KMZ phase.

    Args:
        year: An isolated copy of the retained production inputs.
        output: The isolated destination for logs, checkpoint, and audit.
        working: Temporary state so every replay starts at the same baseline.
        limit: An optional build limit for a smoke run.

    Raises:
        click.ClickException: When the retained logs contain no successful KMZ builds.
    """
    started = time.monotonic()
    inputs = read_inputs(year)
    if not inputs.builds:
        message = "No successful KMZ builds were found in the retained logs."
        raise click.ClickException(message)
    print("Loaded historical inputs", flush=True)
    (working / "sources").mkdir()
    (working / "sources" / "major_cities.gpkg").symlink_to(
        (year / "sources" / "major_cities.gpkg").resolve(),
    )
    records: list[dict[str, object]] = []
    previous_rows: frozenset[int] = frozenset()
    differential_cache: dict[tuple[int, ...], geopandas.GeoDataFrame] = {}
    signal_cache: dict[bytes, tuple[int, bool]] = {}
    summary_cache: dict[str, CachedSummary] = {}
    replayed: list[Build] = []
    covered: list[Build] = []
    prepared = peri_scribe.fire_updates.PreparedUpdates(
        records=(),
        state=peri_scribe.fire_updates.State(),
    )
    for build_index, build in enumerate(inputs.builds):
        rows = frozenset(
            inputs.perimeters.index[inputs.perimeters.available_at <= build.cutoff],
        )
        if not (rows - previous_rows):
            covered.append(build)
            continue
        if limit is not None and len(replayed) >= limit:
            break
        previous_rows = rows
        prepared = prepare_build(
            inputs,
            build,
            year,
            working,
            differential_cache=differential_cache,
            signal_cache=signal_cache,
            summary_cache=summary_cache,
        )
        records.extend(
            {
                **entry,
                "timestamp": build.completed.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            for entry in prepared.records
        )
        peri_scribe.publication.write_state(
            peri_scribe.fire_updates.state_path(working),
            prepared.state,
        )
        replayed.append(build)
        covered.append(build)
        print(
            json.dumps({
                "build": build_index + 1,
                "of": len(inputs.builds),
                "replayed": len(replayed),
                "completed": build.completed.isoformat(),
                "records": len(records),
                "elapsed_seconds": round(time.monotonic() - started, 1),
            }),
            flush=True,
        )
    write_backfill(output / "logs", records)
    peri_scribe.publication.write_state(
        peri_scribe.fire_updates.state_path(output),
        prepared.state,
    )
    audit = backfill_audit(
        year,
        inputs,
        records,
        replayed,
        prepared.state,
        covered=covered,
        limit=limit,
    )
    (output / "derived" / "fire_updates_backfill.json").write_text(
        json.dumps(audit, indent=2) + "\n",
    )
    print(json.dumps(audit), flush=True)


@click.command(help=__doc__)
@click.argument(
    "year",
    type=click.Path(exists=True, file_okay=False, path_type=pathlib.Path),
)
@click.argument(
    "output",
    type=click.Path(file_okay=False, writable=True, path_type=pathlib.Path),
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    help="Replay at most this many builds with new perimeters for a smoke run.",
)
def main(year: pathlib.Path, output: pathlib.Path, limit: int | None) -> None:
    """Require explicit input and staging directories to protect production history.

    Args:
        year: An isolated copy of the retained production inputs.
        output: The isolated destination for logs, checkpoint, and audit.
        limit: An optional positive build limit for a smoke run.
    """
    peri_scribe.logging.configure_logging("error", "error")
    original_location = peri_scribe.report.gathering.fire_location
    locations: dict[bytes | None, str | None] = {}

    def cached_location(
        fire: peri_scribe.presentation.fire_data.FireSummary,
        cities: geopandas.GeoDataFrame,
    ) -> str | None:
        """Reuse the shared location calculation for unchanged fire geometry.

        Args:
            fire: A historical summary.
            cities: The fixed available major cities layer.

        Returns:
            The shared report location phrase.
        """
        geometry = fire.perimeters[-1].geometry if fire.perimeters else fire.point
        if geometry is None or geometry.is_empty:
            geometry = fire.point
        key = None if geometry is None else geometry.wkb
        if key not in locations:
            locations[key] = original_location(fire, cities)
        return locations[key]

    with (
        tempfile.TemporaryDirectory() as working,
        unittest.mock.patch.object(
            peri_scribe.report.gathering,
            "fire_location",
            cached_location,
        ),
        unittest.mock.patch.object(
            peri_scribe.report.gathering,
            "read_cities_layer",
            functools.cache(peri_scribe.report.gathering.read_cities_layer),
        ),
    ):
        reconstruct(year, output, pathlib.Path(working), limit)


if __name__ == "__main__":
    main()
