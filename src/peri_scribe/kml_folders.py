"""Building the KML folder hierarchy for a year's fires.

These helpers append each fire's folder, the latest-perimeters and progression-map
folders, and the top-level active and inactive status folders to a shared
:class:`peri_scribe.kml_geometry.KmlWriter`.
"""

from __future__ import annotations

import typing

import peri_scribe.kml_fire_data
import peri_scribe.kml_geometry
import peri_scribe.kml_icons
import peri_scribe.kml_template
import peri_scribe.kml_tour
import peri_scribe.models
import peri_scribe.perimeter_progression


ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"
TOP_FIRES_BY_NAME_FOLDER_NAME = "Top Fires by Name"
TOP_FIRES_BY_SCORE_FOLDER_NAME = "Top Fires by Score"
TOP_FIRE_COUNT = 25

# The folder inside each fire's latest-perimeters folder that holds the polygons filling
# the fire's interior.
INTERIOR_FOLDER_NAME = "Interior"

# The folder inside each fire's latest-perimeters folder that holds its outline
# perimeters, present only when the fire has more than one.
PERIMETERS_FOLDER_NAME = "Perimeters"


def _outline_placemarks(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fire: peri_scribe.kml_fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    outline_count: int,
    *,
    visible: bool,
) -> None:
    """Append *fire*'s outline perimeters, newest first, to *writer*."""
    for index, template in enumerate(
        peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES,
    ):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        peri_scribe.kml_geometry.perimeter_placemark(
            writer,
            peri_scribe.kml_tour.mapping_placemark_name(perimeter.observation_time),
            style_urls[template.name],
            perimeter.geometry,
            peri_scribe.kml_template.outline_draw_order(outline_count, index),
            description=fire.description,
            visible=visible,
        )


def fire_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fire: peri_scribe.kml_fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append the folder symbolizing *fire* to *writer*.

    The folder leads with the fire's point location, then a "Progression" tour when the
    fire has interior polygons, then its latest, penultimate, and antepenultimate
    perimeters, each shown when the fire's history has one, and finally an ``Interior``
    folder holding the growth rings filling its interior. A fire with more than one
    perimeter holds its outline perimeters in a ``Perimeters`` folder; a fire with a
    single perimeter shows it directly. The interior is drawn from the fire's difference
    rings rather than its complete latest perimeter, so the rings show the interior
    growing; a fire whose rings carry no observation times falls back to its complete
    latest perimeter. The interior lists its rings newest first while the tour replays
    them oldest first.

    Args:
        writer: The writer to append to.
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.
        visible: Whether the folder and its features are visible.
    """
    outline_count = min(
        len(fire.perimeters),
        len(peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES),
    )
    interior_rings = tuple(
        ring for ring in fire.progression_rings if ring.observation_time is not None
    )
    if interior_rings:
        ring_times = tuple(ring.observation_time for ring in interior_rings)
    elif fire.perimeters:
        ring_times = (fire.perimeters[-1].observation_time,)
    else:
        ring_times = ()
    with writer.folder(fire.name, visible=visible) as folder_id:
        if fire.point is not None:
            peri_scribe.kml_geometry.point_placemark(
                writer,
                fire.name,
                style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
                fire.point,
                peri_scribe.kml_template.point_draw_order(outline_count),
                description=fire.description,
                visible=visible,
            )
        if ring_times:
            peri_scribe.kml_tour.progression_tour(
                writer,
                folder_id,
                ring_times,
                visible=visible,
            )
        if outline_count > 1:
            with writer.folder(
                PERIMETERS_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml_icons.perimeters_icon_filename(),
            ):
                _outline_placemarks(
                    writer,
                    fire,
                    style_urls,
                    outline_count,
                    visible=visible,
                )
        else:
            _outline_placemarks(
                writer,
                fire,
                style_urls,
                outline_count,
                visible=visible,
            )
        if interior_rings or fire.perimeters:
            with writer.folder(
                INTERIOR_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml_icons.interior_icon_filename(),
            ):
                if interior_rings:
                    for index in range(len(interior_rings) - 1, -1, -1):
                        ring = interior_rings[index]
                        peri_scribe.kml_geometry.perimeter_placemark(
                            writer,
                            peri_scribe.kml_tour.interior_placemark_name(
                                ring.observation_time,
                            ),
                            style_urls[
                                peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name
                            ],
                            ring.geometry,
                            peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
                            description=fire.description,
                            visible=visible,
                            placemark_id=peri_scribe.kml_tour.interior_ring_id(
                                folder_id,
                                index,
                            ),
                        )
                else:
                    latest_perimeter = fire.perimeters[-1]
                    peri_scribe.kml_geometry.perimeter_placemark(
                        writer,
                        peri_scribe.kml_tour.interior_placemark_name(
                            latest_perimeter.observation_time,
                        ),
                        style_urls[
                            peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name
                        ],
                        latest_perimeter.geometry,
                        peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
                        description=fire.description,
                        visible=visible,
                        placemark_id=peri_scribe.kml_tour.interior_ring_id(
                            folder_id,
                            0,
                        ),
                    )


def latest_perimeters_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append the folder holding each fire's symbolized geometry to *writer*.

    Args:
        writer: The writer to append to.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
        visible: Whether the folder and its features are visible.
    """
    with writer.folder(
        peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
        visible=visible,
    ):
        for fire in fires:
            fire_folder(writer, fire, style_urls, visible=visible)


def progression_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> None:
    """Append the folder holding each fire's progression map to *writer*.

    Each fire gets a folder holding its point location and, when it has growth rings,
    one subfolder per day range it covers; each subfolder holds the fire's growth rings
    from that range, styled by the range's color and marked with a colored icon. A fire
    with no growth rings holds just its point location, so every fire appears in this
    folder exactly as it does in the latest-perimeters folder. The folder and everything
    beneath it loads unchecked, so the progression maps stay hidden until they are
    enabled.

    Args:
        writer: The writer to append to.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
    """
    with writer.folder(
        peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
        visible=False,
    ):
        for fire in fires:
            _progression_fire_folder(writer, fire, style_urls)


def _progression_fire_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fire: peri_scribe.kml_fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Append one fire's progression-map folder to *writer*, hidden."""
    bands = peri_scribe.perimeter_progression.progression_band_rings(
        fire.progression_rings,
    )
    ring_times = tuple(
        ring.observation_time
        for ring in fire.progression_rings
        if ring.observation_time is not None
    )
    ring_count = sum(len(band.rings) for band in bands)
    with writer.folder(fire.name, visible=False) as folder_id:
        if fire.point is not None:
            peri_scribe.kml_geometry.point_placemark(
                writer,
                fire.name,
                style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
                fire.point,
                ring_count,
                description=fire.description,
                visible=False,
            )
        if ring_times:
            peri_scribe.kml_tour.progression_tour(
                writer,
                folder_id,
                ring_times,
                visible=False,
            )
        for position, band in enumerate(bands):
            with writer.folder(
                band.label,
                visible=False,
                item_icon=peri_scribe.kml_icons.progression_icon_filename(
                    band.band_index,
                ),
            ):
                older_ring_count = sum(
                    len(candidate.rings) for candidate in bands[position + 1 :]
                )
                for ring_index, ring in enumerate(band.rings):
                    peri_scribe.kml_geometry.perimeter_placemark(
                        writer,
                        peri_scribe.kml_tour.interior_placemark_name(
                            ring.observation_time,
                        ),
                        style_urls[band.name],
                        ring.geometry,
                        older_ring_count + ring_index,
                        description=fire.description,
                        visible=False,
                        placemark_id=peri_scribe.kml_tour.interior_ring_id(
                            folder_id,
                            older_ring_count + ring_index,
                        ),
                    )


def status_folder_name(status: peri_scribe.models.FireStatus) -> str:
    """Return the top-level folder name for *status*.

    Args:
        status: The fire status.

    Returns:
        The folder name.
    """
    if status is peri_scribe.models.FireStatus.ACTIVE:
        return ACTIVE_FIRES_FOLDER_NAME
    return INACTIVE_FIRES_FOLDER_NAME


def status_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Append the top-level folder for fires of *status* to *writer*.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.

    The inactive fires folder loads unchecked, along with everything beneath it, so
    inactive fires stay hidden until the folder is enabled.
    """
    status_fires = [fire for fire in fires if fire.status is status]
    invisible = status is peri_scribe.models.FireStatus.INACTIVE
    with writer.folder(
        status_folder_name(status),
        visible=not invisible,
        list_item_type="radioFolder",
    ):
        latest_perimeters_folder(
            writer,
            status_fires,
            style_urls,
            visible=not invisible,
        )
        progression_folder(writer, status_fires, style_urls)


def _score_fire(
    entry: peri_scribe.models.FireScoreEntry,
    fires_by_identifier: typing.Mapping[
        str,
        peri_scribe.kml_fire_data.FireGeometry,
    ],
    fires_by_name: typing.Mapping[str, peri_scribe.kml_fire_data.FireGeometry],
) -> peri_scribe.kml_fire_data.FireGeometry | None:
    """Return the geometry matching *entry*, by identifier first and then name.

    Args:
        entry: One saved score.
        fires_by_identifier: The showable fires keyed by each identifier.
        fires_by_name: The showable fires keyed by name.

    Returns:
        The entry's geometry, or None when neither its identifier nor its name matches a
        showable fire.
    """
    fire = (
        fires_by_identifier.get(entry.identifier)
        if entry.identifier is not None
        else None
    )
    if fire is None:
        fire = fires_by_name.get(entry.name)
    return fire


def top_fires(
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
) -> list[peri_scribe.kml_fire_data.FireGeometry]:
    """Return the highest-scoring fires that are present in *fires*.

    Scores can include fires excluded from the map for lacking qualifying geography, so
    the result is matched back to the already-filtered geometry list. A score is matched
    by identifier first, so fires that share a name but not an identity each resolve to
    their own geometry; a score whose identifier matches no fire falls back to its name.

    Args:
        fires: The fires that can be shown in the KMZ.
        scores: The saved score for each fire.

    Returns:
        The top fires in descending score order.
    """
    fires_by_identifier = {
        identifier: fire for fire in fires for identifier in fire.identifiers
    }
    fires_by_name = {fire.name: fire for fire in fires}
    matched = [
        _score_fire(entry, fires_by_identifier, fires_by_name)
        for entry in sorted(
            scores.fires,
            key=lambda entry: (-entry.score, entry.name.casefold()),
        )
    ]
    return [fire for fire in matched if fire is not None][:TOP_FIRE_COUNT]


def top_fires_folder(
    writer: peri_scribe.kml_geometry.KmlWriter,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    name: str,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Append a top-fires folder with the same two views as a status folder."""
    with writer.folder(name, list_item_type="radioFolder"):
        latest_perimeters_folder(writer, fires, style_urls)
        progression_folder(writer, fires, style_urls)
