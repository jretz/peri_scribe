"""Building the KML folder hierarchy for a year's fires.

These helpers append each fire's folder and the top-level active and inactive status
folders to a shared :class:`kml_io.geometry.KmlWriter`.
"""

from __future__ import annotations

import typing

import kml_io.geometry
import peri_scribe.kml.descriptions
import peri_scribe.kml.fire_data
import peri_scribe.kml.icons
import peri_scribe.kml.styles
import peri_scribe.kml.tour
import peri_scribe.models
import peri_scribe.presentation.descriptions


if typing.TYPE_CHECKING:
    import pint


ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"
TOP_FIRES_BY_NAME_FOLDER_NAME = "Top Fires by Name"
TOP_FIRES_BY_SCORE_FOLDER_NAME = "Top Fires by Score"

NEW_NOTABLE_FIRES_FOLDER_NAME = "New, Notable Fires"
TYPE_1_FIRES_FOLDER_NAME = "Type 1 Fires"
FAST_GROWING_FIRES_BY_ACRES_FOLDER_NAME = "Fast Growing Fires (acres)"
FAST_GROWING_FIRES_BY_PERCENT_FOLDER_NAME = "Fast Growing Fires (%)"
MOST_PERSONNEL_FIRES_FOLDER_NAME = "Fires with Most Personnel"

# The folder inside each fire's folder that holds its outline perimeters, present only
# when the fire has more than one.
PERIMETERS_FOLDER_NAME = "Perimeters"

# The folder inside each fire's folder that holds the growth rings filling its interior.
INTERIOR_FOLDER_NAME = "Interior"


def fire_balloon(
    fire: peri_scribe.kml.fire_data.FireGeometry,
    added_area: pint.Quantity[float] | None = None,
) -> str | None:
    """Return the KML balloon text for *fire*'s placemarks.

    Every placemark showing the fire as a whole carries the same balloon describing the
    fire's latest state, so a reader sees the same facts whether they click the point,
    an outline, or a ring. With *added_area*, the text instead opens that balloon's
    table with the area a growth ring added to the fire, so the ring's own growth reads
    above the fire's shared state. A fire without a description has no balloon.

    Args:
        fire: The fire to describe.
        added_area: The area the placemark's growth ring added, or None for the fire's
            own placemarks.

    Returns:
        The balloon's KML description text, or None when the fire has no description.
    """
    if fire.description is None:
        return None
    image_filenames = tuple(image.filename for image in fire.images)
    if added_area is None:
        return peri_scribe.kml.descriptions.description_html(
            fire.description,
            image_filenames,
        )
    return peri_scribe.kml.descriptions.description_html(
        fire.description,
        image_filenames,
        leading_rows=(
            (
                peri_scribe.kml.descriptions.ADDED_AREA_LABEL,
                peri_scribe.presentation.descriptions.format_area(added_area),
            ),
        ),
    )


def outline_placemarks(
    writer: kml_io.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    outline_count: int,
    ring_count: int,
    *,
    visible: bool,
    description: str | None,
) -> None:
    """Append *fire*'s outline perimeters, newest first, to *writer*.

    The outlines draw above the fire's interior rings, so each outline stays visible
    over the rings beneath it. Each outline carries *description*, the balloon the
    fire's own placemarks share.

    Args:
        writer: The writer to append to.
        fire: The fire whose outlines to draw.
        style_urls: The style URL for each template placemark name.
        outline_count: The number of outlines to draw.
        ring_count: The number of interior rings drawn beneath the outlines.
        visible: Whether each outline is visible.
        description: The balloon text each outline shows.
    """
    for index, name in enumerate(peri_scribe.kml.styles.OUTLINED_PERIMETER_NAMES):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        kml_io.geometry.perimeter_placemark(
            writer,
            peri_scribe.kml.tour.mapping_placemark_name(perimeter.observation_time),
            style_urls[name],
            perimeter.geometry,
            peri_scribe.kml.styles.outline_draw_order(outline_count, index)
            + ring_count,
            description=description,
            visible=visible,
        )


def fire_folder(
    writer: kml_io.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append the folder symbolizing *fire* to *writer*.

    The folder leads with the fire's point location, then a "Progression" tour, then its
    latest, penultimate, and antepenultimate perimeter outlines, each shown when the
    fire's history has one, and finally an ``Interior`` folder holding its growth rings
    styled by the color for the day each was observed. A fire with more than one
    perimeter holds its outline perimeters in a ``Perimeters`` folder; a fire with a
    single perimeter shows it directly. A fire with no dated rings falls back to its
    complete latest perimeter, styled with the hottest color, so every fire with
    perimeters appears with an interior. The interior lists its rings newest first while
    the tour replays them oldest first. Each interior ring's balloon opens with the area
    that ring added to the fire, so the ring's own growth reads above the fire's shared
    balloon.

    Args:
        writer: The writer to append to.
        fire: The fire to symbolize.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder and its features are visible.
    """
    outline_count = min(
        len(fire.perimeters),
        len(peri_scribe.kml.styles.OUTLINED_PERIMETER_NAMES),
    )
    rings = list(
        peri_scribe.kml.fire_data.interior_ring_colors(
            fire.progression_rings,
            fire.perimeters,
        ),
    )
    ring_times = tuple(ring.observation_time for ring, _color in rings)
    description = fire_balloon(fire)
    with writer.folder(fire.name, visible=visible) as folder_id:
        if fire.point is not None:
            kml_io.geometry.point_placemark(
                writer,
                fire.name,
                style_urls[peri_scribe.kml.styles.POINT_LOCATION_NAME],
                fire.point,
                peri_scribe.kml.styles.point_draw_order(outline_count) + len(rings),
                description=description,
                visible=visible,
            )
        if ring_times:
            peri_scribe.kml.tour.progression_tour(
                writer,
                folder_id,
                ring_times,
                visible=visible,
            )
        if outline_count > 1:
            with writer.folder(
                PERIMETERS_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml.icons.perimeters_icon_filename(),
            ):
                outline_placemarks(
                    writer,
                    fire,
                    style_urls,
                    outline_count,
                    len(rings),
                    visible=visible,
                    description=description,
                )
        else:
            outline_placemarks(
                writer,
                fire,
                style_urls,
                outline_count,
                len(rings),
                visible=visible,
                description=description,
            )
        if rings:
            added_areas = peri_scribe.kml.fire_data.ring_added_areas(
                tuple(ring for ring, _color in rings),
            )
            with writer.folder(
                INTERIOR_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml.icons.interior_progression_icon_filename(),
            ):
                for index in range(len(rings) - 1, -1, -1):
                    ring, color = rings[index]
                    kml_io.geometry.perimeter_placemark(
                        writer,
                        peri_scribe.kml.tour.interior_placemark_name(
                            ring.observation_time,
                        ),
                        ring_style_urls[color],
                        ring.geometry,
                        index,
                        description=fire_balloon(fire, added_areas[index]),
                        visible=visible,
                        placemark_id=peri_scribe.kml.tour.interior_ring_id(
                            folder_id,
                            index,
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
    writer: kml_io.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    status: peri_scribe.models.FireStatus,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool | None = None,
) -> None:
    """Append the top-level folder for fires of *status* to *writer*.

    The folder holds each fire's folder directly, and each fire loads checked or
    unchecked on its own.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        status: The status whose fires belong in the folder.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder loads checked, or None for the status default
            (active fires load checked, inactive fires load unchecked).

    The inactive fires folder loads unchecked, along with everything beneath it, so
    inactive fires stay hidden until the folder is enabled. A status folder that loads
    unchecked keeps its whole tree hidden, so it carries no visible content and its
    radio button in Google Earth loads off instead of being selected.
    """
    status_fires = [fire for fire in fires if fire.status is status]
    inactive = status is peri_scribe.models.FireStatus.INACTIVE
    if visible is None:
        visible = not inactive
    with writer.folder(status_folder_name(status), visible=visible):
        for fire in status_fires:
            fire_folder(writer, fire, style_urls, ring_style_urls, visible=visible)


def top_fires_folder(
    writer: kml_io.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append a top-fires folder holding each fire's symbolized geometry.

    The folder holds the fires directly, and each fire loads checked or unchecked on its
    own.

    Args:
        writer: The writer to append to.
        fires: The fires to place in the folder.
        name: The folder's name.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        visible: Whether the folder and its features load visible. A folder that loads
            unchecked keeps its whole tree hidden, so it carries no visible content and
            its radio button in Google Earth loads off instead of being selected.
    """
    with writer.folder(name, visible=visible):
        for fire in fires:
            fire_folder(writer, fire, style_urls, ring_style_urls, visible=visible)
