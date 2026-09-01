"""Computing the geometry, extent, and identifier signals for border classification."""

from __future__ import annotations

import datetime
import typing

import shapely
import us.states

import peri_scribe.models
import peri_scribe.perimeters.border_classification
import peri_scribe.units


CALIFORNIA_STATE_ABBREVIATION = us.states.CA.abbr.casefold()


CALIFORNIA_STATE_CODE = f"us-{us.states.CA.abbr.casefold()}"


CALIFORNIA_FIPS_PREFIX = typing.cast("str", us.states.CA.fips)


STATE_CODE_LENGTH = 2


def geometry_signal(
    union: shapely.Geometry | None,
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
    config: peri_scribe.perimeters.border_classification.BorderClassificationConfig,
) -> peri_scribe.perimeters.border_classification.GeometrySignal:
    """Compute the geometry signal for *union* against the California box.

    The portion of the union lying inside the box is inside California (or in the ocean
    or Mexico sliver the box absorbs); the rest lies on the far side of the interstate
    border. A fire crosses the border when it lies on both sides of it. A fire is inside
    when most of it lies within the box.

    Args:
        union: The fire's union geometry in California Albers, or None.
        boundaries: The California box and the interstate border in CA Albers.
        config: The classification thresholds.

    Returns:
        The distance, area measurements, and whether the geometry crosses or is near
        the border, and whether it is inside California.
    """
    if union is None or union.is_empty:
        return peri_scribe.perimeters.border_classification.GeometrySignal(
            distance_to_boundary_in_meters=float("inf"),
            outside_area_fraction=0.0,
            outside_area_in_acres=0.0,
            inside_area_fraction=0.0,
            crosses=False,
            near=False,
            inside=False,
        )
    box, border = boundaries.box, boundaries.border
    # A one-sided fire arrives as the unmerged collection of its parts. Every part lies
    # entirely on one side of the California box, so the signal values are exact without
    # merging: the area fractions are 0 or 1 (overlapping parts would only be merged for
    # the fractions, and one-sided parts leave them at the extremes), the border
    # distance is the minimum over the parts, and a fire entirely outside the box cannot
    # cross it because crossing requires some part inside.
    if isinstance(union, shapely.GeometryCollection) and (
        all(box.contains(part) for part in union.geoms)
        or all(not box.intersects(part) for part in union.geoms)
    ):
        parts = list(union.geoms)
        distance_to_boundary_in_meters = min(part.distance(border) for part in parts)
        # The area fractions follow from which side the parts lie on. A part with no
        # area (a point or line) contributes none, so the union has positive area
        # exactly when some part does, and a one-sided union's fraction is the extreme
        # value when it has area and 0 when it does not.
        has_area = any(part.area > 0 for part in parts)
        if all(box.contains(part) for part in parts):
            inside_area_fraction = 1.0 if has_area else 0.0
            outside_area_fraction = 0.0
            outside_area_in_acres = 0.0
        else:
            inside_area_fraction = 0.0
            outside_area_fraction = 1.0 if has_area else 0.0
            outside_area_in_acres = (
                union.area / peri_scribe.units.SQUARE_METERS_PER_ACRE
            )
        crosses = False
        near = distance_to_boundary_in_meters <= config.near_border_buffer_in_meters
        inside = inside_area_fraction >= config.inside_area_fraction_threshold
        return peri_scribe.perimeters.border_classification.GeometrySignal(
            distance_to_boundary_in_meters=distance_to_boundary_in_meters,
            outside_area_fraction=outside_area_fraction,
            outside_area_in_acres=outside_area_in_acres,
            inside_area_fraction=inside_area_fraction,
            crosses=crosses,
            near=near,
            inside=inside,
        )
    inside_area_in_square_meters = union.intersection(box).area
    total_area_in_square_meters = union.area
    outside_area_in_square_meters = max(
        0.0,
        total_area_in_square_meters - inside_area_in_square_meters,
    )
    inside_area_fraction = (
        inside_area_in_square_meters / total_area_in_square_meters
        if total_area_in_square_meters > 0
        else 0.0
    )
    outside_area_fraction = (
        outside_area_in_square_meters / total_area_in_square_meters
        if total_area_in_square_meters > 0
        else 0.0
    )
    outside_area_in_acres = (
        outside_area_in_square_meters / peri_scribe.units.SQUARE_METERS_PER_ACRE
    )
    crosses = inside_area_fraction > 0 and (
        outside_area_fraction > config.outside_area_fraction_threshold
        or outside_area_in_acres > config.outside_area_threshold_in_acres
    )
    distance_to_boundary_in_meters = union.distance(boundaries.border)
    near = (
        not crosses
        and distance_to_boundary_in_meters <= config.near_border_buffer_in_meters
    )
    inside = inside_area_fraction >= config.inside_area_fraction_threshold
    return peri_scribe.perimeters.border_classification.GeometrySignal(
        distance_to_boundary_in_meters=distance_to_boundary_in_meters,
        outside_area_fraction=outside_area_fraction,
        outside_area_in_acres=outside_area_in_acres,
        inside_area_fraction=inside_area_fraction,
        crosses=crosses,
        near=near,
        inside=inside,
    )


def freshest_observation(
    observations: list[peri_scribe.perimeters.border_classification.FireObservation],
) -> peri_scribe.perimeters.border_classification.FireObservation:
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
        observation: peri_scribe.perimeters.border_classification.FireObservation,
    ) -> tuple[datetime.datetime, int]:
        observed_at = observation.observed_at or peri_scribe.models.EARLIEST_DATETIME
        return observed_at, observation.serial_number

    return max(observations, key=recency_key)


def are_contemporaneous(
    left: peri_scribe.perimeters.border_classification.FireObservation,
    right: peri_scribe.perimeters.border_classification.FireObservation,
    config: peri_scribe.perimeters.border_classification.BorderClassificationConfig,
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
    if left.observed_at is None and right.observed_at is None:
        return True
    if left.observed_at is None or right.observed_at is None:
        return False
    difference = abs(left.observed_at - right.observed_at)
    return difference <= config.contemporaneous_tolerance


def extent_signal(
    observations: list[peri_scribe.perimeters.border_classification.FireObservation],
    config: peri_scribe.perimeters.border_classification.BorderClassificationConfig,
) -> peri_scribe.perimeters.border_classification.ExtentSignal:
    """Compute the FIRIS-versus-WFIGS extent signal.

    The freshest FIRIS perimeter and the freshest WFIGS perimeter are compared when they
    are contemporaneous. A WFIGS perimeter that is substantially larger than the FIRIS
    perimeter of the same fire suggests the fire extends beyond what FIRIS mapped.

    Args:
        observations: The fire's observations.
        config: The classification thresholds.

    Returns:
        The area ratio and whether the extents disagree.
    """
    firis = [
        observation
        for observation in observations
        if observation.source
        is peri_scribe.perimeters.border_classification.FireSourceKind.FIRIS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    wfigs = [
        observation
        for observation in observations
        if observation.source
        is peri_scribe.perimeters.border_classification.FireSourceKind.WFIGS_PERIMETER
        and observation.geometry is not None
        and not observation.geometry.is_empty
    ]
    if not firis or not wfigs:
        return peri_scribe.perimeters.border_classification.ExtentSignal(
            wfigs_to_firis_area_ratio=None,
            disagrees=False,
        )
    firis_freshest = freshest_observation(firis)
    wfigs_freshest = freshest_observation(wfigs)
    if not are_contemporaneous(firis_freshest, wfigs_freshest, config):
        return peri_scribe.perimeters.border_classification.ExtentSignal(
            wfigs_to_firis_area_ratio=None,
            disagrees=False,
        )
    firis_geometry = (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            typing.cast("shapely.Geometry", firis_freshest.geometry),
            peri_scribe.perimeters.border_classification.SOURCE_SPATIAL_REFERENCE_IDS[
                firis_freshest.source
            ],
        )
    )
    wfigs_geometry = (
        peri_scribe.perimeters.border_classification.reproject_to_california_albers(
            typing.cast("shapely.Geometry", wfigs_freshest.geometry),
            peri_scribe.perimeters.border_classification.SOURCE_SPATIAL_REFERENCE_IDS[
                wfigs_freshest.source
            ],
        )
    )
    firis_area = firis_geometry.area
    wfigs_area = wfigs_geometry.area
    ratio = wfigs_area / firis_area if firis_area > 0 else None
    if ratio is None or firis_area <= 0:
        return peri_scribe.perimeters.border_classification.ExtentSignal(
            wfigs_to_firis_area_ratio=ratio,
            disagrees=False,
        )
    symmetric_difference_area = wfigs_geometry.symmetric_difference(
        firis_geometry,
    ).area
    disagrees = wfigs_area > firis_area * config.extent_ratio_threshold or (
        wfigs_area > firis_area
        and symmetric_difference_area
        > firis_area * config.symmetric_difference_fraction_threshold
    )
    return peri_scribe.perimeters.border_classification.ExtentSignal(
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

    A mission that is itself a unique fire identifier (``YYYY-UNIT-######``) carries the
    state in its unit token. Otherwise the state is the mission's leading token when
    that token is a two-letter code, as in ``NV-CCD-BUG``.

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
    observations: list[peri_scribe.perimeters.border_classification.FireObservation],
) -> bool:
    """Return whether any observation carries an out-of-state identifier signal.

    Args:
        observations: The fire's observations.

    Returns:
        True when an identifier, mission, or point of origin names a non-California
        home.
    """
    for observation in observations:
        if out_of_california_unit_from(
            observation.identifiers,
            observation.mission,
        ):
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
