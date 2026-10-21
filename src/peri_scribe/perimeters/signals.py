"""Computing the geometry, extent, and identifier signals for border classification.

[Geometry policy](../../../docs/algorithms/perimeter-geometry-policy.md)
"""

from __future__ import annotations

import datetime
import typing

import shapely
import us.states

import peri_scribe.models
import peri_scribe.perimeters.classification_data
from measurement_units import units


CALIFORNIA_STATE_ABBREVIATION = us.states.CA.abbr.casefold()


CALIFORNIA_STATE_CODE = f"us-{us.states.CA.abbr.casefold()}"


CALIFORNIA_FIPS_PREFIX = typing.cast("str", us.states.CA.fips)


STATE_CODE_LENGTH = 2


def one_sided_collection_evidence(
    parts: list[shapely.Geometry],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
    *,
    inside_box: bool,
) -> peri_scribe.perimeters.classification_data.GeometryEvidence:
    """Measure evidence for a nonempty collection wholly on one side of the box.

    Fractions depend only on whether any part has area. Overlapping parts therefore need
    no union until a caller requests the absolute outside area.

    Args:
        parts: Nonempty parts all contained by, or disjoint from, the box.
        boundaries: The California box and interstate border in California Albers.
        config: The classification thresholds.
        inside_box: Whether every part is contained by the box.

    Returns:
        Exact one-sided distance, fractions, and classification flags.
    """
    distance_to_boundary = (
        min(part.distance(boundaries.border) for part in parts) * units.meters
    )
    has_area = any(part.area > 0 for part in parts)
    inside_area_fraction = 1.0 if inside_box and has_area else 0.0
    outside_area_fraction = 1.0 if not inside_box and has_area else 0.0
    return peri_scribe.perimeters.classification_data.GeometryEvidence(
        distance_to_boundary=distance_to_boundary,
        outside_area_fraction=outside_area_fraction,
        inside_area_fraction=inside_area_fraction,
        crosses=False,
        near=distance_to_boundary <= config.near_border_buffer,
        inside=inside_area_fraction >= config.inside_area_fraction_threshold,
    )


def geometry_signal(
    union: shapely.Geometry | None,
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
) -> peri_scribe.perimeters.classification_data.GeometrySignal:
    """Compute the geometry signal for *union* against the California box.

    The portion of the union lying inside the box is inside California (or in the ocean
    or Mexico sliver the box absorbs); the rest lies on the far side of the interstate
    border. Crossing requires positive inside area and outside area exceeding either
    the configured fraction or absolute-area threshold. The inside flag requires an
    inside fraction at least as large as its configured threshold.

    Args:
        union: The fire's union geometry in California Albers, or None.
        boundaries: The California box and the interstate border in CA Albers.
        config: The classification thresholds.

    Returns:
        The distance, area measurements, and whether the geometry crosses or is near the
        border, and whether it is inside California.
    """
    if union is None or union.is_empty:
        return peri_scribe.perimeters.classification_data.GeometrySignal(
            distance_to_boundary=float("inf") * units.meters,
            outside_area_fraction=0.0,
            outside_area=0.0 * units.Unit("meters ** 2"),
            inside_area_fraction=0.0,
            crosses=False,
            near=False,
            inside=False,
        )
    box = boundaries.box
    # If all parts lie on the same side, their side and nearest border distance can be
    # read directly. There is no need to intersect them with the box, and they cannot
    # cross the border. Measuring outside area still needs a union so overlapping parts
    # count once.
    if isinstance(union, shapely.GeometryCollection) and (
        all(boundaries.prepared_box.contains(part) for part in union.geoms)
        or all(not boundaries.prepared_box.intersects(part) for part in union.geoms)
    ):
        parts = list(union.geoms)
        inside_box = all(boundaries.prepared_box.contains(part) for part in parts)
        evidence = one_sided_collection_evidence(
            parts,
            boundaries,
            config,
            inside_box=inside_box,
        )
        if inside_box:
            outside_area = 0.0 * units.Unit("meters ** 2")
        else:
            outside_area = shapely.union_all(parts).area * units.Unit("meters ** 2")
        return peri_scribe.perimeters.classification_data.GeometrySignal(
            distance_to_boundary=evidence.distance_to_boundary,
            outside_area_fraction=evidence.outside_area_fraction,
            outside_area=outside_area,
            inside_area_fraction=evidence.inside_area_fraction,
            crosses=evidence.crosses,
            near=evidence.near,
            inside=evidence.inside,
        )
    inside_area = union.intersection(box).area * units.Unit("meters ** 2")
    total_area = union.area * units.Unit("meters ** 2")
    outside_area = max(0.0 * units.Unit("meters ** 2"), total_area - inside_area)
    if total_area.magnitude > 0:
        inside_area_fraction = inside_area.magnitude / total_area.magnitude
        outside_area_fraction = outside_area.magnitude / total_area.magnitude
    else:
        inside_area_fraction = 0.0
        outside_area_fraction = 0.0
    crosses = inside_area_fraction > 0 and (
        outside_area_fraction > config.outside_area_fraction_threshold
        or outside_area > config.outside_area_threshold
    )
    distance_to_boundary = union.distance(boundaries.border) * units.meters
    near = not crosses and distance_to_boundary <= config.near_border_buffer
    inside = inside_area_fraction >= config.inside_area_fraction_threshold
    return peri_scribe.perimeters.classification_data.GeometrySignal(
        distance_to_boundary=distance_to_boundary,
        outside_area_fraction=outside_area_fraction,
        outside_area=outside_area,
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def classification_geometry_signal(
    union: shapely.Geometry | None,
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
) -> peri_scribe.perimeters.classification_data.GeometryEvidence:
    """Compute the geometry evidence consumed by the classification policy.

    A wholly outside collection has known fractions and cannot cross the border. Its
    absolute union area is unnecessary for classification. Other geometry keeps the full
    signal calculation so crossing thresholds use the exact outside area.

    Args:
        union: The fire's union geometry in California Albers, or None.
        boundaries: The California box and interstate border in California Albers.
        config: The classification thresholds.

    Returns:
        Exact fractions, flags, and distance for the classification decision.
    """
    if (
        union is not None
        and not union.is_empty
        and isinstance(union, shapely.GeometryCollection)
    ):
        parts = list(union.geoms)
        if all(not boundaries.prepared_box.intersects(part) for part in parts):
            return one_sided_collection_evidence(
                parts,
                boundaries,
                config,
                inside_box=False,
            )
    return geometry_signal(union, boundaries, config)


def prepared_geometry_evidence(
    prepared: peri_scribe.perimeters.classification_data.PreparedObservationGeometry,
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
) -> peri_scribe.perimeters.classification_data.GeometryEvidence:
    """Consume the exact side already established while preparing a collection.

    Args:
        prepared: Geometry and one-sided evidence from the same preparation.
        boundaries: The fixed classification box and border used in preparation.
        config: The classification thresholds.

    Returns:
        Complete classification evidence without repeating known box predicates.
    """
    if prepared.inside_box is not None:
        return one_sided_collection_evidence(
            list(prepared.parts),
            boundaries,
            config,
            inside_box=prepared.inside_box,
        )
    return classification_geometry_signal(prepared.geometry, boundaries, config)


def freshest_observation(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
) -> peri_scribe.perimeters.classification_data.FireObservation:
    """Return the freshest observation in *observations*.

    Recency is decided by observation time first and snapshot serial number second, so a
    perimeter with a later mapping time wins, and equally timed snapshots are broken by
    the newest file.

    Args:
        observations: A non-empty list of observations.

    Returns:
        The freshest observation.

    Raises:
        ValueError: If *observations* is empty.
    """
    if not observations:
        message = "cannot pick the freshest observation from an empty list"
        raise ValueError(message)

    def recency_key(
        observation: peri_scribe.perimeters.classification_data.FireObservation,
    ) -> tuple[datetime.datetime, int]:
        """Use snapshot order to break ties between equally timed observations.

        Args:
            observation: The perimeter observation whose recency is being compared.

        Returns:
            The observation time and serial number, with missing times treated as the
            earliest supported datetime.
        """
        observed_at = observation.observed_at or peri_scribe.models.EARLIEST_DATETIME
        return observed_at, observation.serial_number

    return max(observations, key=recency_key)


def are_contemporaneous(
    left: peri_scribe.perimeters.classification_data.FireObservation,
    right: peri_scribe.perimeters.classification_data.FireObservation,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
) -> bool:
    """Return whether two perimeters were mapped at close enough times to compare.

    Perimeters with no observation time can only be compared to each other, since there
    is no way to tell when either was mapped.

    Args:
        left: One perimeter observation.
        right: The other perimeter observation.
        config: The classification thresholds.

    Returns:
        True when the two perimeters are close enough in time to compare.
    """
    return peri_scribe.models.times_are_contemporaneous(
        left.observed_at,
        right.observed_at,
        config.contemporaneous_tolerance,
    )


def extent_signal(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig,
    *,
    projections: peri_scribe.perimeters.classification_data.ProjectionCache
    | None = None,
) -> peri_scribe.perimeters.classification_data.ExtentSignal:
    """Compute the FIRIS-versus-WFIGS extent signal.

    The freshest FIRIS perimeter and the freshest WFIGS perimeter are compared when they
    are contemporaneous. A WFIGS perimeter that is substantially larger than the FIRIS
    perimeter of the same fire suggests the fire extends beyond what FIRIS mapped.

    Args:
        observations: The fire's observations.
        config: The classification thresholds.
        projections: Exact projections shared with this fire's geometry evidence.

    Returns:
        The area ratio and whether the extents disagree.
    """
    firis = [
        observation
        for observation in observations
        if observation.source
        is peri_scribe.perimeters.classification_data.FireSourceKind.FIRIS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    wfigs = [
        observation
        for observation in observations
        if observation.source
        is peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    if not firis or not wfigs:
        return peri_scribe.perimeters.classification_data.ExtentSignal(
            wfigs_to_firis_area_ratio=None,
            disagrees=False,
        )
    firis_freshest = freshest_observation(firis)
    wfigs_freshest = freshest_observation(wfigs)
    if not are_contemporaneous(firis_freshest, wfigs_freshest, config):
        return peri_scribe.perimeters.classification_data.ExtentSignal(
            wfigs_to_firis_area_ratio=None,
            disagrees=False,
        )
    if projections is None:
        projections = peri_scribe.perimeters.classification_data.ProjectionCache()
    firis_geometry = projections.project(
        typing.cast("shapely.Geometry", firis_freshest.geometry),
        peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
            firis_freshest.source
        ],
    )
    wfigs_geometry = projections.project(
        typing.cast("shapely.Geometry", wfigs_freshest.geometry),
        peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
            wfigs_freshest.source
        ],
    )
    firis_area = firis_geometry.area
    wfigs_area = wfigs_geometry.area
    ratio = wfigs_area / firis_area if firis_area > 0 else None
    if ratio is None or firis_area <= 0:
        return peri_scribe.perimeters.classification_data.ExtentSignal(
            wfigs_to_firis_area_ratio=ratio,
            disagrees=False,
        )
    symmetric_difference_area = wfigs_geometry.symmetric_difference(firis_geometry).area
    disagrees = wfigs_area > firis_area * config.extent_ratio_threshold or (
        wfigs_area > firis_area
        and symmetric_difference_area
        > firis_area * config.symmetric_difference_fraction_threshold
    )
    return peri_scribe.perimeters.classification_data.ExtentSignal(
        wfigs_to_firis_area_ratio=ratio,
        disagrees=disagrees,
    )


def unit_state_code_is_out_of_california(token: str) -> bool:
    """Return whether *token* embeds a non-California US state code.

    Args:
        token: A fire unit or mission token.

    Returns:
        True when the token starts with a recognized state code other than California's.

    Examples:
        >>> unit_state_code_is_out_of_california("NV-CCD")
        True

        >>> unit_state_code_is_out_of_california("CA-LNU")
        False
    """
    folded = token.casefold()
    if len(folded) < STATE_CODE_LENGTH:
        return False
    state_code = folded[:STATE_CODE_LENGTH]
    return (
        us.states.lookup(state_code) is not None
        and state_code != CALIFORNIA_STATE_ABBREVIATION
    )


def state_tokens_from_mission(mission: str) -> list[str]:
    """Return the state-code tokens a mission code can carry.

    A mission accepted by :func:`peri_scribe.models.is_unique_fire_identifier` carries
    the state candidate in its unit token. Otherwise the candidate is the mission's
    leading token when it has two characters, as in ``NV-CCD-BUG``.

    Args:
        mission: The fire's mapping mission code.

    Returns:
        The mission's state-code candidate tokens.

    Examples:
        >>> state_tokens_from_mission("2025-NV-123456")
        ['NV']

        >>> state_tokens_from_mission("NV-CCD-BUG")
        ['NV']
    """
    if peri_scribe.models.is_unique_fire_identifier(mission):
        return [mission.split("-")[1]]
    first = mission.split("-", 1)[0]
    return [first] if len(first) == STATE_CODE_LENGTH else []


def out_of_california_unit_from(
    identifiers: frozenset[str],
    mission: str | None,
) -> bool:
    """Return whether a fire identifier or mission names an out-of-California unit.

    Args:
        identifiers: The fire's identifiers.
        mission: The fire's mapping mission code, or None.

    Returns:
        True when any identifier unit or mission token embeds a non-California state.
    """
    tokens = [
        identifier.split("-")[1]
        for identifier in identifiers
        if peri_scribe.models.is_unique_fire_identifier(identifier)
    ]
    if mission is not None:
        tokens.extend(state_tokens_from_mission(mission))
    return any(unit_state_code_is_out_of_california(token) for token in tokens)


def identifier_signal(
    observations: list[peri_scribe.perimeters.classification_data.FireObservation],
) -> bool:
    """Return whether any observation carries an out-of-state identifier signal.

    Args:
        observations: The fire's observations.

    Returns:
        True when an identifier, mission, or point of origin names a non-California
        home.
    """
    for observation in observations:
        if out_of_california_unit_from(observation.identifiers, observation.mission):
            return True
        if (
            observation.point_of_origin_state is not None
            and observation.point_of_origin_state.casefold() != CALIFORNIA_STATE_CODE
        ):
            return True
        if (
            observation.point_of_origin_fips is not None
            and not observation.point_of_origin_fips.startswith(CALIFORNIA_FIPS_PREFIX)
        ):
            return True
    return False
