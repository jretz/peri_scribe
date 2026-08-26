"""Building the KML folder hierarchy for a year's fires.

These helpers assemble each fire's folder, the latest-perimeters and progression-map
folders, and the top-level active and inactive status folders.
"""

from __future__ import annotations

import typing

import simplekml

import peri_scribe.kml_fire_data
import peri_scribe.kml_geometry
import peri_scribe.kml_icons
import peri_scribe.kml_template
import peri_scribe.kml_tour
import peri_scribe.models
import peri_scribe.perimeter_progression


ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"

# The folder inside each fire's latest-perimeters folder that holds the polygons
# filling the fire's interior.
INTERIOR_FOLDER_NAME = "Interior"

# The folder inside each fire's latest-perimeters folder that holds its outline
# perimeters, present only when the fire has more than one.
PERIMETERS_FOLDER_NAME = "Perimeters"


def fire_folder(
    container: simplekml.Container,
    fire: peri_scribe.kml_fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder symbolizing *fire* to *container*.

    The folder leads with the fire's point location, then a "Progression" tour when the
    fire has interior polygons, then its latest, penultimate, and antepenultimate
    perimeters, each shown when the fire's history has one, and finally an ``Interior``
    folder holding the growth rings filling its interior. A fire with more than one
    perimeter holds its outline perimeters in a ``Perimeters`` folder; a fire with a
    single perimeter shows it directly. The interior is drawn from the fire's difference
    rings rather than its complete latest perimeter, so the rings show the interior
    growing; a fire whose rings carry no observation times falls back to its complete
    latest perimeter. The interior lists its rings newest first while the tour replays
    them oldest first. Draw orders put the filled latest area on the bottom, stack the
    outline perimeters from oldest to newest, and draw the point location last so its
    icon is never covered.

    Args:
        container: The folder that holds the fire's folder.
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(name=fire.name)
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
    if fire.point is not None:
        peri_scribe.kml_geometry.point_placemark(
            folder,
            fire.name,
            style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
            fire.point,
            peri_scribe.kml_template.point_draw_order(outline_count),
            description=fire.description,
        )
    if ring_times:
        peri_scribe.kml_tour.progression_tour(folder, ring_times)
    perimeters_folder = folder
    if outline_count > 1:
        perimeters_folder = folder.newfolder(name=PERIMETERS_FOLDER_NAME)
        perimeters_folder.liststyle.itemicon.href = (
            peri_scribe.kml_icons.perimeters_icon_filename()
        )
    for index, template in enumerate(
        peri_scribe.kml_template.OUTLINED_PERIMETER_TEMPLATES,
    ):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        peri_scribe.kml_geometry.perimeter_placemark(
            perimeters_folder,
            peri_scribe.kml_tour.mapping_placemark_name(perimeter.observation_time),
            style_urls[template.name],
            perimeter.geometry,
            peri_scribe.kml_template.outline_draw_order(outline_count, index),
            description=fire.description,
        )
    if interior_rings or fire.perimeters:
        interior_folder = folder.newfolder(name=INTERIOR_FOLDER_NAME)
        interior_folder.liststyle.itemicon.href = (
            peri_scribe.kml_icons.interior_icon_filename()
        )
        if interior_rings:
            for index in range(len(interior_rings) - 1, -1, -1):
                ring = interior_rings[index]
                placemark = peri_scribe.kml_geometry.perimeter_placemark(
                    interior_folder,
                    peri_scribe.kml_tour.interior_placemark_name(ring.observation_time),
                    style_urls[peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name],
                    ring.geometry,
                    peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
                    description=fire.description,
                )
                peri_scribe.kml_tour.assign_placemark_id(
                    placemark,
                    peri_scribe.kml_tour.interior_ring_id(folder, index),
                )
        else:
            latest_perimeter = fire.perimeters[-1]
            placemark = peri_scribe.kml_geometry.perimeter_placemark(
                interior_folder,
                peri_scribe.kml_tour.interior_placemark_name(
                    latest_perimeter.observation_time,
                ),
                style_urls[peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name],
                latest_perimeter.geometry,
                peri_scribe.kml_template.LATEST_AREA_DRAW_ORDER,
                description=fire.description,
            )
            peri_scribe.kml_tour.assign_placemark_id(
                placemark,
                peri_scribe.kml_tour.interior_ring_id(folder, 0),
            )


def latest_perimeters_folder(
    container: simplekml.Container,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder holding each fire's symbolized geometry to *container*.

    Args:
        container: The folder that holds the perimeters folder.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(
        name=peri_scribe.kml_template.LATEST_PERIMETERS_FOLDER_NAME,
    )
    for fire in fires:
        fire_folder(folder, fire, style_urls)


def progression_folder(
    container: simplekml.Container,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the folder holding each fire's progression map to *container*.

    Each fire gets a folder holding its point location and, when it has growth rings,
    one subfolder per day range it covers; each subfolder holds the fire's growth rings
    from that range, styled by the range's color and marked with a colored icon. A fire
    with no growth rings holds just its point location, so every fire appears in this
    folder exactly as it does in the latest-perimeters folder. The fire folder leads
    with its point location, then a "Progression" tour when it has rings, replaying them
    oldest first exactly as the latest-perimeters folder does, but its animated updates
    target the rings inside the day-range subfolders rather than rings in the same
    folder. Draw orders put the oldest ring on the bottom, stack the rings from oldest
    to newest, and draw the point location last so its icon is never covered. The folder
    loads unchecked, along with everything beneath it, so the progression maps stay
    hidden until they are enabled.

    Args:
        container: The folder that holds the progression maps folder.
        fires: The fires to place in the folder.
        style_urls: The style URL for each template placemark name.
    """
    folder = container.newfolder(
        name=peri_scribe.perimeter_progression.PROGRESSION_MAPS_FOLDER_NAME,
    )
    for fire in fires:
        bands = peri_scribe.perimeter_progression.progression_band_rings(
            fire.progression_rings,
        )
        fire_folder = folder.newfolder(name=fire.name)
        ring_times = tuple(
            ring.observation_time
            for ring in fire.progression_rings
            if ring.observation_time is not None
        )
        ring_count = sum(len(band.rings) for band in bands)
        if fire.point is not None:
            peri_scribe.kml_geometry.point_placemark(
                fire_folder,
                fire.name,
                style_urls[peri_scribe.kml_template.POINT_LOCATION_NAME],
                fire.point,
                ring_count,
                description=fire.description,
            )
        if ring_times:
            peri_scribe.kml_tour.progression_tour(fire_folder, ring_times)
        for position, band in enumerate(bands):
            subfolder = fire_folder.newfolder(name=band.label)
            subfolder.liststyle.itemicon.href = (
                peri_scribe.kml_icons.progression_icon_filename(
                    band.band_index,
                )
            )
            older_ring_count = sum(
                len(candidate.rings) for candidate in bands[position + 1 :]
            )
            for ring_index, ring in enumerate(band.rings):
                placemark = peri_scribe.kml_geometry.perimeter_placemark(
                    subfolder,
                    peri_scribe.kml_tour.interior_placemark_name(ring.observation_time),
                    style_urls[band.name],
                    ring.geometry,
                    older_ring_count + ring_index,
                    description=fire.description,
                )
                peri_scribe.kml_tour.assign_placemark_id(
                    placemark,
                    peri_scribe.kml_tour.interior_ring_id(
                        fire_folder,
                        older_ring_count + ring_index,
                    ),
                )
    set_invisible(folder)


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


def set_invisible(container: simplekml.Container) -> None:
    """Set *container* and every feature beneath it to unchecked.

    Each feature's own ``visibility`` is set to zero, not only the container's, so the
    whole tree below the container stays unchecked when the container is re-enabled in
    Google Earth. Tours are marked too: simplekml gives a tour no ``visibility``
    property, so the element is written directly, and the tour stays unchecked like
    every other feature under the hidden folder.

    Args:
        container: The folder to hide.
    """
    container.visibility = 0
    for feature in container.allfeatures:
        if isinstance(feature, simplekml.GxTour):
            feature._kml["visibility"] = 0  # ruff: ignore[private-member-access]
        else:
            feature.visibility = 0


def set_radio_folder(folder: simplekml.Folder) -> None:
    """Make *folder*'s children display as radio buttons in the Places panel.

    A radio folder shows one child checked at a time, so its children are alternatives
    the reader picks between rather than independent layers.

    Args:
        folder: The folder to mark.
    """
    folder.liststyle.listitemtype = simplekml.ListItemType.radiofolder


def status_folder(
    container: simplekml.Container,
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
) -> None:
    """Add the top-level folder for fires of *status* to *container*.

    Args:
        container: The document that holds the status folder.
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.

    The inactive fires folder loads unchecked, along with everything beneath
    it, so inactive fires stay hidden until the folder is enabled.
    """
    folder = container.newfolder(name=status_folder_name(status))
    set_radio_folder(folder)
    status_fires = [fire for fire in fires if fire.status is status]
    latest_perimeters_folder(folder, status_fires, style_urls)
    progression_folder(folder, status_fires, style_urls)
    if status is peri_scribe.models.FireStatus.INACTIVE:
        set_invisible(folder)
