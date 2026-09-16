"""One typed catalogue defines observable work and its permitted hierarchy."""

import collections.abc
import dataclasses
import enum
import types

import peri_scribe.pipeline_stages


class Phase(enum.StrEnum):
    """Stable identifiers connect execution events with the monitor's phase tree."""

    FIRE_COLLECTION = "fire-collection"
    COLLECT_FEED = "collect-feed"
    CHECK_METADATA = "check-metadata"
    READ_CURRENT_STATE = "read-current-state"
    QUERY_FEATURES = "query-features"
    CONVERT_FEATURES = "convert-features"
    COMPARE_FEATURES = "compare-features"
    WRITE_SNAPSHOT = "write-snapshot"
    UPDATE_CURRENT_STATE = "update-current-state"
    EVACUATION_CHECK = "evacuation-check"
    PUBLICATION_GATE = "publication-gate"
    DEFERRED_FETCH = "deferred-fetch"
    SOURCE_INDEX = "source-index"
    LOAD_AND_GROUP_SOURCES = "load-and-group-sources"
    READ_SOURCES = "read-sources"
    GROUP_SOURCES = "group-sources"
    CLASSIFY_FIRES = "classify-fires"
    WRITE_INDEX = "write-index"
    EXTERNAL_SOURCE_REFRESH = "external-source-refresh"
    COLLECT_EXTERNAL_SOURCE = "collect-external-source"
    BUILDINGS_DATABASE = "buildings-database"
    NORMALIZE_DATETIMES = "normalize-datetimes"
    ADMINISTRATIVE_BOUNDARIES = "administrative-boundaries"
    FULL_HISTORY = "full-history"
    LOAD_REUSABLE_HISTORY = "load-reusable-history"
    RECONSTRUCT_GEOGRAPHY = "reconstruct-geography"
    DIFFERENTIAL_HISTORY = "differential-history"
    SELECT_CURRENT_AREAS = "select-current-areas"
    SPATIAL_SIGNALS = "spatial-signals"
    PREPARE_FIRE_HISTORIES = "prepare-fire-histories"
    PREPARE_FIRE_GEOMETRIES = "prepare-fire-geometries"
    PREPARE_PLOT_IMAGES = "prepare-plot-images"
    SERIALIZE_AND_WRITE_KMZ = "serialize-and-write-kmz"
    BUILD_KML = "build-kml"


type Identifier = Phase | peri_scribe.pipeline_stages.Stage


CHILDREN: collections.abc.Mapping[Identifier, tuple[Identifier, ...]] = (
    types.MappingProxyType({
        peri_scribe.pipeline_stages.Stage.FETCH: (
            Phase.FIRE_COLLECTION,
            Phase.SOURCE_INDEX,
            Phase.EXTERNAL_SOURCE_REFRESH,
            Phase.EVACUATION_CHECK,
            Phase.PUBLICATION_GATE,
            Phase.DEFERRED_FETCH,
        ),
        Phase.FIRE_COLLECTION: (Phase.COLLECT_FEED,),
        Phase.COLLECT_FEED: (
            Phase.CHECK_METADATA,
            Phase.READ_CURRENT_STATE,
            Phase.QUERY_FEATURES,
            Phase.CONVERT_FEATURES,
            Phase.COMPARE_FEATURES,
            Phase.WRITE_SNAPSHOT,
            Phase.UPDATE_CURRENT_STATE,
        ),
        Phase.EVACUATION_CHECK: (Phase.COLLECT_EXTERNAL_SOURCE,),
        Phase.DEFERRED_FETCH: (Phase.SOURCE_INDEX, Phase.EXTERNAL_SOURCE_REFRESH),
        Phase.SOURCE_INDEX: (
            Phase.LOAD_AND_GROUP_SOURCES,
            Phase.CLASSIFY_FIRES,
            Phase.WRITE_INDEX,
        ),
        Phase.LOAD_AND_GROUP_SOURCES: (Phase.READ_SOURCES, Phase.GROUP_SOURCES),
        Phase.EXTERNAL_SOURCE_REFRESH: (
            Phase.COLLECT_EXTERNAL_SOURCE,
            Phase.ADMINISTRATIVE_BOUNDARIES,
        ),
        Phase.COLLECT_EXTERNAL_SOURCE: (
            Phase.BUILDINGS_DATABASE,
            Phase.QUERY_FEATURES,
            Phase.CONVERT_FEATURES,
            Phase.NORMALIZE_DATETIMES,
            Phase.COMPARE_FEATURES,
            Phase.WRITE_SNAPSHOT,
        ),
        peri_scribe.pipeline_stages.Stage.GEOGRAPHY: (
            Phase.FULL_HISTORY,
            Phase.DIFFERENTIAL_HISTORY,
        ),
        Phase.FULL_HISTORY: (
            Phase.LOAD_AND_GROUP_SOURCES,
            Phase.LOAD_REUSABLE_HISTORY,
            Phase.RECONSTRUCT_GEOGRAPHY,
        ),
        peri_scribe.pipeline_stages.Stage.SCORE: (
            Phase.SELECT_CURRENT_AREAS,
            Phase.SPATIAL_SIGNALS,
        ),
        peri_scribe.pipeline_stages.Stage.KMZ: (
            Phase.PREPARE_FIRE_HISTORIES,
            Phase.PREPARE_FIRE_GEOMETRIES,
            Phase.SERIALIZE_AND_WRITE_KMZ,
        ),
        Phase.PREPARE_FIRE_GEOMETRIES: (Phase.PREPARE_PLOT_IMAGES,),
        Phase.SERIALIZE_AND_WRITE_KMZ: (Phase.BUILD_KML,),
        peri_scribe.pipeline_stages.Stage.REPORTS: (Phase.PREPARE_FIRE_HISTORIES,),
    })
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Segment:
    """Branch identity keeps repeated work on different sources independent."""

    phase: str
    branch: str = ""


type Path = tuple[Segment, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Branches:
    """Configured sources supply instance names without duplicating phase names."""

    feeds: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    evacuations: str = ""


def branch_name(identifier: str, fields: collections.abc.Mapping[str, object]) -> str:
    """Attach instance identity at the owning phase rather than every nested event.

    Args:
        identifier: The phase being entered.
        fields: Its structured execution context.

    Returns:
        The feed or source name, or an empty string for work without instances.
    """
    field = {
        Phase.COLLECT_FEED: "feed",
        Phase.COLLECT_EXTERNAL_SOURCE: "source",
    }.get(identifier)
    return str(fields.get(field, "")) if field else ""


def planned_paths(
    branches: Branches,
    *,
    gated: bool,
    roots: tuple[Identifier, ...] = tuple(peri_scribe.pipeline_stages.Stage),
    parent: Path = (),
) -> tuple[Path, ...]:
    """Expand the shared hierarchy before work begins so pending phases are visible.

    Args:
        branches: Configured feed and external-source names.
        gated: Whether publication uses the evacuation check and deferred fetch.
        roots: The phases to expand at this level.
        parent: The enclosing phase instances.

    Returns:
        Every planned phase instance in display order.
    """
    result: list[Path] = []
    for identifier in roots:
        names = ("",)
        if identifier == Phase.COLLECT_FEED:
            names = branches.feeds or names
        if identifier == Phase.COLLECT_EXTERNAL_SOURCE:
            names = branches.sources or names
            if parent and parent[-1].phase == Phase.EVACUATION_CHECK:
                names = (branches.evacuations,)
            elif gated:
                names = tuple(name for name in names if name != branches.evacuations)
        children = CHILDREN.get(identifier, ())
        if identifier == peri_scribe.pipeline_stages.Stage.FETCH:
            excluded = (
                (Phase.SOURCE_INDEX, Phase.EXTERNAL_SOURCE_REFRESH)
                if gated
                else (
                    Phase.EVACUATION_CHECK,
                    Phase.PUBLICATION_GATE,
                    Phase.DEFERRED_FETCH,
                )
            )
            children = tuple(child for child in children if child not in excluded)
        for name in names:
            path = (*parent, Segment(phase=identifier, branch=name))
            result.append(path)
            result.extend(
                planned_paths(branches, gated=gated, roots=children, parent=path),
            )
    return tuple(result)
