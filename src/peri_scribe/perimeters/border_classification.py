"""Classify fires relative to the California state boundary.

A fire is classified as INSIDE_CALIFORNIA, INSIDE_CALIFORNIA_NEAR_BORDER,
CROSSES_CALIFORNIA_BORDER, OUTSIDE_CALIFORNIA_NEAR_BORDER, or OUTSIDE_CALIFORNIA by
combining three signals. The primary signal compares the fire's geometry with a
"California box" that traces the border California shares with its neighboring US states
(Arizona, Nevada, and Oregon) and closes well out into the Pacific Ocean and Mexico, so
maritime and international borders are absorbed into the box. The secondary signal
compares contemporaneous FIRIS and WFIGS perimeters, where a WFIGS perimeter that is
substantially larger suggests the fire extends beyond what FIRIS mapped. The tertiary
signal flags out-of-state fire units and points of origin. CROSSES_CALIFORNIA_BORDER
requires the geometry to span the California border; the weaker signals only ever
support the near-border classifications.
"""

from __future__ import annotations

import pathlib
import typing

import shapely

import peri_scribe.models
import peri_scribe.perimeters.classification_data
import peri_scribe.perimeters.signals
import peri_scribe.sources.administrative_boundaries
import peri_scribe.sources.borders
import peri_scribe.sources.snapshots
import spatial_data.reference


def source_kind_for_feed_name(
    feed_name: str,
) -> peri_scribe.perimeters.classification_data.FireSourceKind:
    """Return the source kind for a source directory name.

    Args:
        feed_name: The feed's name, which doubles as its source directory name.

    Returns:
        The source kind the feed represents.

    Raises:
        ValueError: If the feed name does not name a known fire source.

    Examples:
        >>> source_kind_for_feed_name("CA_Perimeters_NIFC_FIRIS")
        <FireSourceKind.FIRIS_PERIMETER: 'firis_perimeter'>
    """
    if "CA_Perimeters_NIFC_FIRIS" in feed_name:
        return peri_scribe.perimeters.classification_data.FireSourceKind.FIRIS_PERIMETER
    if "WFIGS_Interagency_Perimeters" in feed_name:
        return peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_PERIMETER
    if "WFIGS_Incident_Locations" in feed_name:
        return peri_scribe.perimeters.classification_data.FireSourceKind.WFIGS_LOCATION
    message = f"unknown fire source directory {feed_name!r}"
    raise ValueError(message)


def snapshot_serial_number(path: pathlib.Path) -> int:
    """Return the snapshot serial number encoded in a GeoPackage filename.

    Args:
        path: The GeoPackage path.

    Returns:
        The serial number from the filename.

    Examples:
        >>> snapshot_serial_number(pathlib.Path("000012,lastEdit=1.gpkg"))
        12
    """
    return peri_scribe.sources.snapshots.SourceFile.from_path(path).serial_number


def load_boundaries(
    year_directory: pathlib.Path,
) -> peri_scribe.perimeters.classification_data.Boundaries:
    """Load the California box and the interstate border, in California Albers.

    Args:
        year_directory: The year directory that holds the ``sources`` directory.

    Returns:
        The California box and the interstate border in California Albers.
    """
    border = peri_scribe.sources.administrative_boundaries.load_border_geometry(
        year_directory,
    )
    box = peri_scribe.sources.borders.california_box_polygon(border)
    return peri_scribe.perimeters.classification_data.Boundaries(
        box=peri_scribe.perimeters.classification_data.reproject_to_california_albers(
            box,
            spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
        ),
        border=peri_scribe.perimeters.classification_data.reproject_to_california_albers(
            border,
            spatial_data.reference.WGS84_SPATIAL_REFERENCE_ID,
        ),
    )


def unioned_observation_geometry(
    observations: typing.Iterable[
        peri_scribe.perimeters.classification_data.FireObservation
    ],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> shapely.Geometry | None:
    """Return a geometry describing the observations in California Albers.

    Observations of the same fire frequently repeat the same mapped geometry, so
    byte-identical (source, geometry) pairs are collapsed before re-projection: the
    re-projection is deterministic, and the union of the distinct geometries is the same
    shape as the union of all of them. A single distinct geometry is returned as itself,
    since the union of one geometry is the geometry.

    When every distinct geometry lies entirely on one side of the California box, the
    parts are returned unmerged as a collection instead of being unioned. The
    classification's geometry signal recognizes such a one-sided collection and reads
    the exact signal values from the parts: a one-sided fire's area fractions are 0 or
    1, its border distance is the minimum over the parts, and it cannot cross the
    border. Only a fire whose geometry straddles the box needs the true union, since
    overlapping parts on both sides change the area fractions.

    Args:
        observations: The fire's observations.
        boundaries: The California box and interstate border in CA Albers.

    Returns:
        The union (or unmerged collection) of the distinct geometries in California
        Albers, or None when there are none.
    """
    seen: set[
        tuple[peri_scribe.perimeters.classification_data.FireSourceKind, bytes]
    ] = set()
    distinct: list[
        tuple[
            peri_scribe.perimeters.classification_data.FireObservation,
            shapely.Geometry,
        ]
    ] = []
    for observation in observations:
        geometry = observation.geometry
        if geometry is None or geometry.is_empty:
            continue
        key = (observation.source, geometry.wkb)
        if key in seen:
            continue
        seen.add(key)
        distinct.append((observation, geometry))
    geometries: list[shapely.Geometry] = []
    for observation, geometry in distinct:
        geometries.append(
            peri_scribe.perimeters.classification_data.reproject_to_california_albers(
                geometry,
                peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                    observation.source
                ],
            ),
        )
    if not geometries:
        return None
    if len(geometries) == 1:
        return geometries[0]
    box = boundaries.box
    if all(box.contains(geometry) for geometry in geometries) or all(
        not box.intersects(geometry) for geometry in geometries
    ):
        return shapely.GeometryCollection(geometries)
    return shapely.union_all(geometries)


def classify(
    *,
    geometry: peri_scribe.perimeters.classification_data.GeometrySignal,
    extent: peri_scribe.perimeters.classification_data.ExtentSignal,
    identifier: bool,
) -> peri_scribe.models.FireClassification:
    """Combine the three signals into a border classification.

    CROSSES_CALIFORNIA_BORDER requires the geometry to span the California border. A
    fire that does not cross is INSIDE_CALIFORNIA or OUTSIDE_CALIFORNIA, with the
    near-border variants when it is within the near-border buffer or the FIRIS and WFIGS
    extents disagree. The identifier signal only ever appears in the evidence; it never
    changes the classification on its own.

    Args:
        geometry: The geometry signal.
        extent: The extent disagreement signal.
        identifier: Whether the identifier signal fired.

    Returns:
        The classification with its evidence.
    """
    signals: list[peri_scribe.models.BorderSignal] = []
    if geometry.crosses:
        signals.append(peri_scribe.models.BorderSignal.GEOMETRY_OUTSIDE)
    if geometry.near:
        signals.append(peri_scribe.models.BorderSignal.GEOMETRY_NEAR)
    if extent.disagrees:
        signals.append(peri_scribe.models.BorderSignal.EXTENT_DISAGREEMENT)
    if identifier:
        signals.append(peri_scribe.models.BorderSignal.IDENTIFIER_UNIT)

    if geometry.crosses:
        classification = (
            peri_scribe.models.BorderClassification.CROSSES_CALIFORNIA_BORDER
        )
    elif geometry.near or extent.disagrees:
        if geometry.inside:
            classification = (
                peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA_NEAR_BORDER
            )
        else:
            classification = (
                peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA_NEAR_BORDER
            )
    elif geometry.inside:
        classification = peri_scribe.models.BorderClassification.INSIDE_CALIFORNIA
    else:
        classification = peri_scribe.models.BorderClassification.OUTSIDE_CALIFORNIA

    return peri_scribe.models.FireClassification(
        classification=classification,
        outside_area_fraction=geometry.outside_area_fraction,
        inside_area_fraction=geometry.inside_area_fraction,
        wfigs_to_firis_area_ratio=extent.wfigs_to_firis_area_ratio,
        signals=signals,
    )


def classify_fire(
    *,
    records: typing.Iterable[peri_scribe.models.FireRecord],
    record_paths: typing.Iterable[pathlib.Path],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    config: peri_scribe.perimeters.classification_data.BorderClassificationConfig
    | None = None,
) -> peri_scribe.models.FireClassification:
    """Classify one fire from its records and source files.

    Args:
        records: The fire's records, aligned with *record_paths*.
        record_paths: The GeoPackage file each record came from.
        boundaries: The California polygon and border in California Albers.
        config: The classification thresholds. Defaults to the standard thresholds.

    Returns:
        The fire's border classification and evidence.
    """
    if config is None:
        config = peri_scribe.perimeters.classification_data.BorderClassificationConfig()
    observations = [
        peri_scribe.perimeters.classification_data.FireObservation(
            source=source_kind_for_feed_name(
                peri_scribe.sources.snapshots.source_name_from_snapshot_path(path),
            ),
            geometry=record.geometry,
            observed_at=record.observed_at,
            serial_number=snapshot_serial_number(path),
            identifiers=record.identifiers,
            mission=record.mission,
            point_of_origin_state=record.point_of_origin_state,
            point_of_origin_fips=record.point_of_origin_fips,
        )
        for record, path in zip(records, record_paths, strict=True)
    ]
    return classify(
        geometry=peri_scribe.perimeters.signals.geometry_signal(
            unioned_observation_geometry(observations, boundaries),
            boundaries,
            config,
        ),
        extent=peri_scribe.perimeters.signals.extent_signal(observations, config),
        identifier=peri_scribe.perimeters.signals.identifier_signal(observations),
    )
