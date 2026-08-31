"""Building the KML folder hierarchy for a year's fires.

These helpers append each fire's folder and the top-level active and inactive status
folders to a shared :class:`peri_scribe.kml.geometry.KmlWriter`.
"""

from __future__ import annotations

import typing

import peri_scribe.kml.colormap
import peri_scribe.kml.fire_data
import peri_scribe.kml.geometry
import peri_scribe.kml.icons
import peri_scribe.kml.styles
import peri_scribe.kml.tour
import peri_scribe.models
import peri_scribe.perimeters.progression


ACTIVE_FIRES_FOLDER_NAME = "Active Fires"
INACTIVE_FIRES_FOLDER_NAME = "Inactive Fires"
TOP_FIRES_BY_NAME_FOLDER_NAME = "Top Fires by Name"
TOP_FIRES_BY_SCORE_FOLDER_NAME = "Top Fires by Score"
TOP_FIRE_COUNT = 25

# The folder inside each fire's folder that holds its outline perimeters, present only
# when the fire has more than one.
PERIMETERS_FOLDER_NAME = "Perimeters"

# The folder inside each fire's folder that holds the growth rings filling its interior.
INTERIOR_FOLDER_NAME = "Interior"


def outline_placemarks(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    outline_count: int,
    ring_count: int,
    *,
    visible: bool,
) -> None:
    """Append *fire*'s outline perimeters, newest first, to *writer*.

    The outlines draw above the fire's interior rings, so each outline stays visible
    over the rings beneath it.

    Args:
        writer: The writer to append to.
        fire: The fire whose outlines to draw.
        style_urls: The style URL for each template placemark name.
        outline_count: The number of outlines to draw.
        ring_count: The number of interior rings drawn beneath the outlines.
        visible: Whether each outline is visible.
    """
    for index, name in enumerate(peri_scribe.kml.styles.OUTLINED_PERIMETER_NAMES):
        if len(fire.perimeters) <= index:
            break
        perimeter = fire.perimeters[-(index + 1)]
        peri_scribe.kml.geometry.perimeter_placemark(
            writer,
            peri_scribe.kml.tour.mapping_placemark_name(perimeter.observation_time),
            style_urls[name],
            perimeter.geometry,
            peri_scribe.kml.styles.outline_draw_order(outline_count, index)
            + ring_count,
            description=fire.description,
            visible=visible,
        )


def fire_folder(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fire: peri_scribe.kml.fire_data.FireGeometry,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    visible: bool = True,
) -> None:
    """Append the folder symbolizing *fire* to *writer*.

    The folder leads with the fire's point location, then a "Progression" tour, then
    its latest, penultimate, and antepenultimate perimeter outlines, each shown when the
    fire's history has one, and finally an ``Interior`` folder holding its growth rings
    styled by the color for the day each was observed. A fire with more than one
    perimeter holds its outline perimeters in a ``Perimeters`` folder; a fire with a
    single perimeter shows it directly. A fire with no dated rings falls back to its
    complete latest perimeter, styled with the hottest color, so every fire with
    perimeters appears with an interior. The interior lists its rings newest first while
    the tour replays them oldest first.

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
    colored_rings = peri_scribe.kml.colormap.progression_ring_colors(
        fire.progression_rings,
    )
    if colored_rings:
        rings = [
            (ring, peri_scribe.kml.colormap.color_hex(rgb))
            for ring, rgb in colored_rings
        ]
        ring_times = tuple(ring.observation_time for ring, _color in rings)
    elif fire.perimeters:
        latest_perimeter = fire.perimeters[-1]
        rings = [
            (
                peri_scribe.perimeters.progression.Ring(
                    geometry=latest_perimeter.geometry,
                    observation_time=latest_perimeter.observation_time,
                ),
                peri_scribe.kml.colormap.color_hex(
                    peri_scribe.kml.colormap.TURBO_RAMP[-1],
                ),
            ),
        ]
        ring_times = (latest_perimeter.observation_time,)
    else:
        rings = []
        ring_times = ()
    with writer.folder(fire.name, visible=visible) as folder_id:
        if fire.point is not None:
            peri_scribe.kml.geometry.point_placemark(
                writer,
                fire.name,
                style_urls[peri_scribe.kml.styles.POINT_LOCATION_NAME],
                fire.point,
                peri_scribe.kml.styles.point_draw_order(outline_count) + len(rings),
                description=fire.description,
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
                )
        else:
            outline_placemarks(
                writer,
                fire,
                style_urls,
                outline_count,
                len(rings),
                visible=visible,
            )
        if rings:
            with writer.folder(
                INTERIOR_FOLDER_NAME,
                visible=visible,
                item_icon=peri_scribe.kml.icons.interior_progression_icon_filename(),
            ):
                for index in range(len(rings) - 1, -1, -1):
                    ring, color = rings[index]
                    peri_scribe.kml.geometry.perimeter_placemark(
                        writer,
                        peri_scribe.kml.tour.interior_placemark_name(
                            ring.observation_time,
                        ),
                        ring_style_urls[color],
                        ring.geometry,
                        index,
                        description=fire.description,
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
    writer: peri_scribe.kml.geometry.KmlWriter,
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
    with writer.folder(
        status_folder_name(status),
        visible=visible,
    ):
        for fire in status_fires:
            fire_folder(writer, fire, style_urls, ring_style_urls, visible=visible)


def score_fire(
    entry: peri_scribe.models.FireScoreEntry,
    fires_by_identifier: typing.Mapping[
        str,
        peri_scribe.kml.fire_data.FireGeometry,
    ],
    fires_by_name: typing.Mapping[str, peri_scribe.kml.fire_data.FireGeometry],
) -> peri_scribe.kml.fire_data.FireGeometry | None:
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
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
) -> list[peri_scribe.kml.fire_data.FireGeometry]:
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
        score_fire(entry, fires_by_identifier, fires_by_name)
        for entry in sorted(
            scores.fires,
            key=lambda entry: (-entry.score, entry.name.casefold()),
        )
    ]
    return [fire for fire in matched if fire is not None][:TOP_FIRE_COUNT]


def top_fires_folder(
    writer: peri_scribe.kml.geometry.KmlWriter,
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
