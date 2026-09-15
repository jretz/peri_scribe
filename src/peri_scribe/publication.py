"""Compare saved mapping updates with the inputs of a completed local KMZ."""

from __future__ import annotations

import dataclasses
import datetime
import enum
import hashlib
import math
import pathlib
import tempfile
import typing

import pydantic
import shapely
import structlog

import peri_scribe.geo.package
import peri_scribe.geo.parsing
import peri_scribe.models
import peri_scribe.perimeters.size_filtering
import peri_scribe.perimeters.versions
import peri_scribe.sources.external_data
import peri_scribe.sources.external_sources
import peri_scribe.sources.feeds
import peri_scribe.sources.snapshots
import peri_scribe.units
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import geopandas
    import pint


logger = structlog.get_logger()


@dataclasses.dataclass(frozen=True, kw_only=True)
class Threshold:
    """A mapped-area change or elapsed publication interval permits a build.

    Args:
        area: The minimum absolute mapped-area change that triggers publication.
        interval: The maximum elapsed time since publication before pending data builds.
    """

    area: pint.Quantity[float]
    interval: datetime.timedelta


class FileStamp(pydantic.BaseModel):
    """Native filesystem metadata identifies the exact file a checkpoint covers.

    Args:
        size: The file size in bytes.
        modified_nanoseconds: The modification time in nanoseconds since the epoch.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    size: int
    modified_nanoseconds: int


class Mapping(pydantic.BaseModel):
    """A raw mapping's measurement, identity and original collection provenance.

    Args:
        source_file: The snapshot path relative to the sources directory.
        object_id: The source row identifier, or None when unavailable.
        identifiers: The fire identifiers associated with this mapping.
        name: The source's fire name.
        observed_at: The effective mapping date, or None when unavailable.
        captured_at: The earliest local capture of this fire's geometry.
        serial: The source snapshot's serial number.
        shape: The normalized geometry digest, or an empty string for missing geometry.
        area_square_meters: The raw geodesic area, or None when it cannot be measured.
        collapsed: Whether the measured geometry fails the shared perimeter size filter.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    source_file: str
    object_id: int | None
    identifiers: tuple[str, ...]
    name: str
    observed_at: pydantic.AwareDatetime | None
    captured_at: pydantic.AwareDatetime
    serial: int
    shape: str
    area_square_meters: float | None = pydantic.Field(ge=0, allow_inf_nan=False)
    collapsed: bool = False

    @property
    def area(self) -> pint.Quantity[float] | None:
        """Restore physical units at the persistence boundary.

        Returns:
            The measurement with area units, or None when it cannot be measured.
        """
        if self.area_square_meters is None:
            return None
        return self.area_square_meters * units.meters**2


class Collection(pydantic.BaseModel):
    """Measurement caches advance with downloads, independently of publication.

    Args:
        version: The persisted cache format version.
        files: File identities keyed by snapshot paths relative to the sources
            directory.
        mappings: Raw mapping measurements keyed by their snapshot paths.
        evacuations: The saved evacuation file's identity, or None when absent.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    version: typing.Literal[2] = 2
    files: dict[str, FileStamp] = pydantic.Field(default_factory=dict)
    mappings: dict[str, tuple[Mapping, ...]] = pydantic.Field(default_factory=dict)
    evacuations: FileStamp | None = None


class PublishedFire(pydantic.BaseModel):
    """Aliases follow the derived fire identity; only displayed mappings set area.

    Args:
        identifiers: The identifiers and aliases belonging to the derived fire.
        name: The derived fire's display name.
        mapping: The displayed source mapping, or None when the fire was excluded.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    identifiers: tuple[str, ...]
    name: str
    mapping: Mapping | None


class Publication(pydantic.BaseModel):
    """A checkpoint belongs to one completed KMZ and its frozen source inventory.

    Args:
        version: The persisted checkpoint format version.
        created_at: The time the completed local KMZ was acknowledged.
        output: The completed KMZ's file identity.
        files: The source snapshot inventory processed for this publication.
        fires: The published baselines keyed by derived fire identity.
        evacuations: The processed evacuation file's identity, or None when absent.
    """

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)
    version: typing.Literal[1] = 1
    created_at: pydantic.AwareDatetime
    output: FileStamp
    files: dict[str, FileStamp]
    fires: dict[str, PublishedFire]
    evacuations: FileStamp | None = None


class Reason(enum.StrEnum):
    """Stable decision reasons make skips and required rebuilds distinguishable."""

    NO_CHANGES = "no unpublished data"
    BELOW_THRESHOLD = "area below threshold and timer not due"
    AREA = "mapped area changed"
    TIMER = "publication timer expired"
    NO_PUBLICATION = "missing or invalid publication checkpoint"
    SOURCE_HISTORY = "previously processed source history changed"
    UNCERTAIN_MAPPING = "mapping cannot be compared reliably"
    EVACUATIONS = "evacuation data changed"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Decision:
    """Explain why the remaining pipeline should run or be deferred.

    Args:
        proceed: Whether the remaining pipeline should run.
        reason: The condition that determined whether publication is needed.
        change: The signed area change with the greatest absolute magnitude.
        fire: The fire associated with the area change, or None when not applicable.
    """

    proceed: bool
    reason: Reason
    change: pint.Quantity[float] = dataclasses.field(
        default_factory=lambda: 0.0 * units.acres,
    )
    fire: str | None = None


def file_stamp(path: pathlib.Path) -> FileStamp:
    """Read the identity used to detect replacement or removal of saved inputs.

    Args:
        path: The file whose identity is needed for comparison.

    Returns:
        The file size and last modification time in native filesystem units.
    """
    status = path.stat()
    return FileStamp(size=status.st_size, modified_nanoseconds=status.st_mtime_ns)


def collection_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep disposable measurements beside their authoritative source snapshots.

    Args:
        year_directory: The year directory containing the source snapshots.

    Returns:
        The disposable measurement-cache path.
    """
    return year_directory / "sources" / "publication_cache.json"


def publication_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Keep successful publication separate from collection and failed-stage state.

    Args:
        year_directory: The year directory containing the completed pipeline outputs.

    Returns:
        The successful publication checkpoint path.
    """
    return year_directory / "publication_state.json"


def read_state[State: pydantic.BaseModel](
    path: pathlib.Path,
    state_type: type[State],
) -> State | None:
    """Missing or corrupt state cannot authorize a skip.

    Args:
        path: The persisted state file to validate.
        state_type: The model defining the expected state format.

    Returns:
        The validated state, or None when it is missing or corrupt.
    """
    try:
        return state_type.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except ValueError as error:
        logger.warning("Invalid publication state", path=path, error=str(error))
        return None


def write_state(path: pathlib.Path, state: pydantic.BaseModel) -> None:
    """Preserve the last complete checkpoint if a state write fails.

    Args:
        path: The destination of the complete state file.
        state: The validated state to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = pathlib.Path(directory) / path.name
        temporary.write_text(state.model_dump_json())
        temporary.replace(path)


def read_publication(
    year_directory: pathlib.Path,
    output_path: pathlib.Path,
) -> Publication | None:
    """Only the KMZ named by the checkpoint can supply a published baseline.

    Args:
        year_directory: The year directory containing the publication checkpoint.
        output_path: The current KMZ whose identity must match the checkpoint.

    Returns:
        The valid checkpoint, or None when it does not match the KMZ.
    """
    state = read_state(publication_path(year_directory), Publication)
    if state is None:
        return None
    try:
        output = file_stamp(output_path)
    except FileNotFoundError:
        return None
    return state if state.output == output else None


def mapping_order(mapping: Mapping) -> tuple[datetime.datetime, int, int]:
    """Order mappings by observation time to preserve newer surveys.

    Args:
        mapping: The source observation to order relative to other mappings.

    Returns:
        The effective observation date, snapshot serial, and object identifier.
    """
    return (
        mapping.observed_at or peri_scribe.models.EARLIEST_DATETIME,
        mapping.serial,
        mapping.object_id if mapping.object_id is not None else -1,
    )


def shape_measurement(geometry: shapely.Geometry | None) -> tuple[str, float | None]:
    """Consistent ring orientation prevents multipart cancellation in geodesic area.

    Args:
        geometry: The raw mapping geometry in WGS84, or None when unavailable.

    Returns:
        The normalized shape digest and area in square meters. Missing or empty geometry
        has an empty digest; an unmeasurable area is None.
    """
    if geometry is None or geometry.is_empty:
        return "", None
    shape = hashlib.sha256(shapely.normalize(geometry).wkb).hexdigest()
    if not geometry.is_valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return shape, None
    area = peri_scribe.units.area(shapely.orient_polygons(geometry))
    return shape, area.m_as("meters ** 2") if math.isfinite(area.magnitude) else None


def snapshot_mappings(
    path: pathlib.Path,
    sources_directory: pathlib.Path,
    captured_at: datetime.datetime,
) -> tuple[Mapping, ...]:
    """Measure only saved perimeter rows; incident attributes remain timer inputs.

    Args:
        path: The saved source snapshot containing perimeter observations.
        sources_directory: The root for each mapping's relative source path.
        captured_at: The local snapshot capture time, before first-capture
            deduplication.

    Returns:
        Raw perimeter measurements and source provenance for this snapshot.
    """
    measurements: list[Mapping] = []
    for feed, source_frame in peri_scribe.geo.package.layers_by_feed(path):
        if feed == peri_scribe.sources.feeds.WFIGS_INCIDENT_LOCATIONS_FEED:
            continue
        frame = source_frame.to_crs(peri_scribe.models.WGS84_SPATIAL_REFERENCE_ID)
        geometry_name = str(frame.geometry.name)
        for _, row in frame.iterrows():
            record = peri_scribe.geo.parsing.fire_record_from_row(
                row,
                feed,
                row[geometry_name],
            )
            if record is None:
                continue
            source = peri_scribe.perimeters.versions.source_observation_from_row(
                peri_scribe.geo.package.FireRowRecord(
                    record=record,
                    object_id=peri_scribe.geo.parsing.object_id_from(row),
                    source_name=feed.name,
                    attributes=peri_scribe.geo.parsing.row_attributes(
                        row,
                        geometry_name,
                    ),
                ),
                path,
                sources_directory,
            )
            shape, area = shape_measurement(record.geometry)
            measurements.append(
                Mapping(
                    source_file=source.source_file,
                    object_id=source.object_id,
                    identifiers=tuple(sorted(record.identifiers)),
                    name=record.name,
                    observed_at=peri_scribe.perimeters.versions.effective_time(source),
                    captured_at=captured_at,
                    serial=source.serial_number,
                    shape=shape,
                    area_square_meters=area,
                    collapsed=(
                        peri_scribe.perimeters.size_filtering.area_is_implausibly_small(
                            None if area is None else area * units.meters**2,
                            source.attributes,
                        )
                    ),
                ),
            )
    return tuple(measurements)


def collect(year_directory: pathlib.Path) -> Collection:
    """Reuse unchanged measurements while keeping skipped downloads available.

    Args:
        year_directory: The year directory containing saved sources and their cache.

    Returns:
        The saved inventory and measurements, including unacknowledged updates.
    """
    sources_directory = peri_scribe.sources.snapshots.sources_directory_path(
        year_directory,
    )
    files = {
        str(path.relative_to(sources_directory)): file_stamp(path)
        for path in peri_scribe.sources.snapshots.geo_package_files(sources_directory)
    }
    cached = read_state(collection_path(year_directory), Collection) or Collection()
    evacuation_path = peri_scribe.sources.external_data.output_path(
        year_directory,
        peri_scribe.sources.external_sources.EVACUATIONS_SOURCE,
    )
    evacuations = file_stamp(evacuation_path) if evacuation_path.exists() else None
    if (
        cached.files == files
        and set(cached.mappings) == set(files)
        and cached.evacuations == evacuations
    ):
        return cached
    mappings: dict[str, tuple[Mapping, ...]] = {}
    for relative, stamp in files.items():
        if cached.files.get(relative) == stamp and relative in cached.mappings:
            mappings[relative] = cached.mappings[relative]
        else:
            captured_at = datetime.datetime.fromtimestamp(
                (stamp.modified_nanoseconds * units.nanoseconds).m_as("seconds"),
                datetime.UTC,
            )
            mappings[relative] = snapshot_mappings(
                sources_directory / relative,
                sources_directory,
                captured_at,
            )
    state = Collection(
        files=files,
        mappings=first_captures(mappings),
        evacuations=evacuations,
    )
    write_state(collection_path(year_directory), state)
    return state


def first_captures(
    snapshots: dict[str, tuple[Mapping, ...]],
) -> dict[str, tuple[Mapping, ...]]:
    """Attribute-only republication must not move a geometry's first-capture clock.

    Args:
        snapshots: Source paths and their mapping measurements, including repeat shapes.

    Returns:
        Measurements carrying the earliest capture of their fire and shape.
    """
    captured: dict[tuple[str, str], datetime.datetime] = {}
    for mappings in snapshots.values():
        for mapping in mappings:
            for identifier in mapping.identifiers:
                key = identifier, mapping.shape
                captured[key] = min(
                    captured.get(key, mapping.captured_at),
                    mapping.captured_at,
                )
    return {
        path: tuple(
            mapping.model_copy(
                update={
                    "captured_at": min(
                        (
                            captured[identifier, mapping.shape]
                            for identifier in mapping.identifiers
                        ),
                        default=mapping.captured_at,
                    ),
                },
            )
            for mapping in mappings
        )
        for path, mappings in snapshots.items()
    }


def candidate_fires(
    mappings: typing.Iterable[Mapping],
    published: Publication,
) -> dict[str, tuple[Mapping, PublishedFire | None]] | None:
    """Shared identifiers permit cheap grouping; ambiguity requires a build.

    Collapsed polygons cannot become published mappings, so they must not displace
    acceptable candidates or trigger area-based publication.

    Args:
        mappings: Unpublished source observations to compare with the baselines.
        published: The completed publication supplying fire identities and baselines.

    Returns:
        Latest acceptable candidates and their published baselines, or None for
        ambiguity.
    """
    aliases = {
        identifier: key
        for key, fire in published.fires.items()
        for identifier in fire.identifiers
    }
    candidates: dict[str, tuple[Mapping, PublishedFire | None]] = {}
    for mapping in mappings:
        if mapping.collapsed:
            continue
        matches = {aliases[i] for i in mapping.identifiers if i in aliases}
        if not mapping.identifiers or len(matches) > 1:
            return None
        key = (
            next(iter(matches))
            if matches
            else "id:"
            + (peri_scribe.models.canonical_fire_identifier(mapping.identifiers) or "")
        )
        aliases.update(dict.fromkeys(mapping.identifiers, key))
        baseline = published.fires.get(key)
        previous = candidates.get(key)
        if previous is None or mapping_order(mapping) > mapping_order(previous[0]):
            candidates[key] = mapping, baseline
    return candidates


def decide(
    collection: Collection,
    published: Publication | None,
    threshold: Threshold,
    now: datetime.datetime,
) -> Decision:
    """Publication advances only after a build, so several small changes accumulate.

    Args:
        collection: The latest saved source inventory and raw mapping measurements.
        published: The last valid publication checkpoint, or None when unavailable.
        threshold: The mapped-area change and elapsed-time requirements.
        now: The current timezone-aware time for the publication interval check.

    Returns:
        Whether publication is required, together with its reason and area signal.
    """
    if published is None:
        return Decision(proceed=True, reason=Reason.NO_PUBLICATION)
    if collection.evacuations != published.evacuations:
        return Decision(proceed=True, reason=Reason.EVACUATIONS)
    if any(
        collection.files.get(path) != stamp for path, stamp in published.files.items()
    ):
        return Decision(proceed=True, reason=Reason.SOURCE_HISTORY)
    pending = set(collection.files) - set(published.files)
    if not pending:
        return Decision(proceed=False, reason=Reason.NO_CHANGES)
    candidates = candidate_fires(
        (mapping for path in sorted(pending) for mapping in collection.mappings[path]),
        published,
    )
    decision = mapping_decision(candidates, threshold)
    if not decision.proceed and now - published.created_at >= threshold.interval:
        return dataclasses.replace(decision, proceed=True, reason=Reason.TIMER)
    return decision


def mapping_decision(
    candidates: dict[str, tuple[Mapping, PublishedFire | None]] | None,
    threshold: Threshold,
) -> Decision:
    """Compare the latest mapping with its published source on the same area basis.

    Args:
        candidates: Latest mappings paired with their published fire, or None when fire
            identity is ambiguous. A missing published fire has a zero baseline.
        threshold: The policy supplying the minimum absolute mapped-area change.

    Returns:
        The largest absolute change, or a required build for ambiguous mappings.
    """
    if candidates is None:
        return Decision(proceed=True, reason=Reason.UNCERTAIN_MAPPING)
    largest = Decision(proceed=False, reason=Reason.BELOW_THRESHOLD)
    for current, fire in candidates.values():
        baseline = fire.mapping if fire is not None else None
        if baseline is not None and mapping_order(current) < mapping_order(baseline):
            continue
        if current.area is None or (baseline is not None and baseline.area is None):
            return Decision(proceed=True, reason=Reason.UNCERTAIN_MAPPING)
        previous_area = baseline.area if baseline is not None else 0.0 * units.acres
        change = current.area - previous_area
        if abs(change) > abs(largest.change):
            reached = abs(change) >= threshold.area or math.isclose(
                abs(change).m_as("meters ** 2"),
                threshold.area.m_as("meters ** 2"),
                rel_tol=1e-12,
            )
            largest = Decision(
                proceed=reached,
                reason=Reason.AREA if reached else Reason.BELOW_THRESHOLD,
                change=change,
                fire=current.name,
            )
    return largest


def published_fires(
    collection: Collection,
    perimeters: geopandas.GeoDataFrame,
    index: peri_scribe.models.FireIndex,
) -> dict[str, PublishedFire]:
    """Use each displayed mapping's raw source measurement as its baseline.

    Args:
        collection: The source inventory frozen for the completed geography stage.
        perimeters: Derived perimeter histories with source-row provenance.
        index: The fire index identifying which fires are included in the KMZ.

    Returns:
        The per-fire raw measurements represented by the displayed histories.

    Raises:
        ValueError: When a displayed source row cannot be identified uniquely.
    """
    included_identifiers = {
        identifier
        for entry in index.fires
        for identifier in [entry.identifier, *entry.aliases]
        if identifier is not None
    }
    included_names = {entry.name for entry in index.fires if entry.identifier is None}
    fires: dict[str, PublishedFire] = {}
    for _, row in perimeters.iterrows():
        identifier = peri_scribe.geo.parsing.normalize_identifier(
            row["fire_identifier"],
        )
        name = str(row["fire_name"])
        key = "id:" + identifier if identifier is not None else "name:" + name
        aliases_value = row["fire_aliases"]
        aliases = {
            alias
            for value in (
                []
                if peri_scribe.geo.parsing.is_missing(aliases_value)
                else str(aliases_value).split(",")
            )
            if (alias := peri_scribe.geo.parsing.normalize_identifier(value))
            is not None
        }
        if identifier is not None:
            aliases.add(identifier)
        object_id = peri_scribe.geo.parsing.numeric_value(row["source_objectid"])
        matches = [
            mapping
            for mapping in collection.mappings.get(str(row["source_file"]), ())
            if mapping.object_id == object_id
        ]
        if len(matches) != 1:
            message = f"Cannot identify published mapping source for {name}"
            raise ValueError(message)
        mapping = matches[0]
        aliases.update(mapping.identifiers)
        if key in fires:
            aliases.update(fires[key].identifiers)
        included = bool(aliases & included_identifiers) or (
            identifier is None and name in included_names
        )
        fires[key] = PublishedFire(
            identifiers=tuple(sorted(aliases)),
            name=name,
            mapping=mapping if included else None,
        )
    return fires


def commit(
    year_directory: pathlib.Path,
    output_path: pathlib.Path,
    collection: Collection,
    fires: dict[str, PublishedFire],
) -> None:
    """Commit the frozen inputs only after the complete KMZ replaced its predecessor.

    Args:
        year_directory: The year directory where the publication checkpoint belongs.
        output_path: The completed local KMZ whose identity the checkpoint records.
        collection: The frozen source inventory used to generate the KMZ.
        fires: Published mapping baselines keyed by derived fire identity.
    """
    state = Publication(
        created_at=datetime.datetime.now(datetime.UTC),
        output=file_stamp(output_path),
        files=collection.files,
        fires=fires,
        evacuations=collection.evacuations,
    )
    write_state(publication_path(year_directory), state)
