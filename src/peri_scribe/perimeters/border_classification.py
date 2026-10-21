"""Classify fires relative to the California interstate boundary.

The classification determines whether a fire is inside California, outside it, or
crossing its border, with near-border variants for fires on either side. These
distinctions help choose between FIRIS and WFIGS mapping.

The main evidence comes from geometry. A "California box" follows the borders with
Arizona, Nevada, and Oregon, then closes well into the Pacific Ocean and Mexico. This
keeps maritime and international boundaries from counting as interstate crossings.

A second signal compares FIRIS and WFIGS perimeters mapped at similar times. A
substantially larger WFIGS perimeter suggests FIRIS may not have mapped the full fire.
That disagreement can support a near-border classification, but crossing requires
geometry on both sides. Out-of-state units and points of origin are retained as
additional evidence; they do not change the classification.

[Geometry policy](../../../docs/algorithms/perimeter-geometry-policy.md)
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
import spatial_data.geometry_pool
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


def prepare_observation_geometry(
    observations: typing.Iterable[
        peri_scribe.perimeters.classification_data.FireObservation
    ],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
    *,
    projections: peri_scribe.perimeters.classification_data.ProjectionCache
    | None = None,
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> peri_scribe.perimeters.classification_data.PreparedObservationGeometry:
    """Retain projected geometry and exact one-sided collection evidence together.

    Snapshots often repeat the same mapped shape. Collapse byte-identical (source,
    geometry) pairs before projection: projecting the same pair twice gives the same
    result, and duplicates add nothing to a union. A single distinct geometry can be
    returned directly.

    When all the distinct geometries lie entirely on the same side of the California
    box, return them as a collection. The geometry signal can obtain their border
    distance from the nearest part and their inside and outside fractions from their
    shared side. A positive-area collection has fractions of 0 and 1; a collection with
    no area has fractions of 0. Neither can cross the border.

    Geometry on both sides needs a union, because overlaps affect the area fractions.
    The geometry signal also unions an outside collection when measuring its absolute
    area, so overlapping parts are counted once.

    Args:
        observations: The fire's observations.
        boundaries: The California box and interstate border in CA Albers.
        projections: Exact object/CRS projections shared by classification consumers.
        geometry_keys: Compact exact WKB classes owned by the source read.

    Returns:
        Geometry in California Albers and a known side for one-sided collections.
    """
    if projections is None:
        projections = peri_scribe.perimeters.classification_data.ProjectionCache()
    if geometry_keys is None:
        geometry_keys = spatial_data.geometry_pool.GeometryKeys()
    seen: set[
        tuple[
            peri_scribe.perimeters.classification_data.FireSourceKind,
            spatial_data.geometry_pool.GeometryKey,
        ]
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
        key = (observation.source, geometry_keys.key(geometry))
        if key in seen:
            continue
        seen.add(key)
        distinct.append((observation, geometry))
    geometries: list[shapely.Geometry] = []
    for observation, geometry in distinct:
        geometries.append(
            projections.project(
                geometry,
                peri_scribe.perimeters.classification_data.SOURCE_SPATIAL_REFERENCE_IDS[
                    observation.source
                ],
            ),
        )
    if not geometries:
        return peri_scribe.perimeters.classification_data.PreparedObservationGeometry(
            geometry=None,
        )
    if len(geometries) == 1:
        return peri_scribe.perimeters.classification_data.PreparedObservationGeometry(
            geometry=geometries[0],
        )
    box = boundaries.prepared_box
    inside_box: bool | None = None
    if all(box.contains(geometry) for geometry in geometries):
        inside_box = True
    elif all(not box.intersects(geometry) for geometry in geometries):
        inside_box = False
    if inside_box is not None:
        return peri_scribe.perimeters.classification_data.PreparedObservationGeometry(
            geometry=shapely.GeometryCollection(geometries),
            parts=tuple(geometries),
            inside_box=inside_box,
        )
    return peri_scribe.perimeters.classification_data.PreparedObservationGeometry(
        geometry=shapely.union_all(geometries),
    )


def unioned_observation_geometry(
    observations: typing.Iterable[
        peri_scribe.perimeters.classification_data.FireObservation
    ],
    boundaries: peri_scribe.perimeters.classification_data.Boundaries,
) -> shapely.Geometry | None:
    """Return exact projected coverage, retaining one-sided parts as a collection.

    Args:
        observations: The fire's observations, including repeated source shapes.
        boundaries: The California box and interstate border in California Albers.

    Returns:
        The projected geometry, or None without nonempty observations.
    """
    return prepare_observation_geometry(observations, boundaries).geometry


def classify(
    *,
    geometry: peri_scribe.perimeters.classification_data.GeometryEvidence,
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
    geometry_keys: spatial_data.geometry_pool.GeometryKeys | None = None,
) -> peri_scribe.models.FireClassification:
    """Classify one fire from its records and source files.

    Args:
        records: The fire's records, aligned with *record_paths*.
        record_paths: The GeoPackage file each record came from.
        boundaries: The California box and interstate border in California Albers.
        config: The classification thresholds. Defaults to the standard thresholds.
        geometry_keys: Exact encoding classes retained by this source-read owner.

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
    projections = peri_scribe.perimeters.classification_data.ProjectionCache()
    prepared = prepare_observation_geometry(
        observations,
        boundaries,
        projections=projections,
        geometry_keys=geometry_keys,
    )
    return classify(
        geometry=peri_scribe.perimeters.signals.prepared_geometry_evidence(
            prepared,
            boundaries,
            config,
        ),
        extent=peri_scribe.perimeters.signals.extent_signal(
            observations,
            config,
            projections=projections,
        ),
        identifier=peri_scribe.perimeters.signals.identifier_signal(observations),
    )
