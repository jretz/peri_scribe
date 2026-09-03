"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). Symbolization styles and placemark
style URLs are defined in code; progression-map ring colors are computed from the Turbo
colormap.
"""

from __future__ import annotations

import datetime
import pathlib
import typing
import zipfile

import structlog

import peri_scribe.fires.differential
import peri_scribe.fires.files
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.geo.reading
import peri_scribe.kml.colormap
import peri_scribe.kml.fire_data
import peri_scribe.kml.folders
import peri_scribe.kml.geometry
import peri_scribe.kml.icons
import peri_scribe.kml.selection
import peri_scribe.kml.styles
import peri_scribe.models


if typing.TYPE_CHECKING:
    import geopandas


logger = structlog.get_logger()


MAPS_DIRECTORY_NAME = "maps"

KMZ_DOCUMENT_FILENAME = "doc.kml"

# DEFLATE is the compression Google Earth expects inside a KMZ. Level 6 is used instead
# of the maximum 9: the output is within 1% of level 9's size but compresses several
# times faster, and the plot PNGs are already compressed (so they are stored without
# recompressing rather than passed through DEFLATE a second time).
KMZ_COMPRESSION = zipfile.ZIP_DEFLATED
KMZ_COMPRESSION_LEVEL = 6


def year_from(year_directory: pathlib.Path) -> int:
    """Return the year named by *year_directory*.

    Args:
        year_directory: The year directory, whose name is the year.

    Returns:
        The year as an integer.

    Examples:
        >>> year_from(pathlib.Path("data/2025"))
        2025
    """
    return int(year_directory.name)


def kmz_filename(year: int) -> str:
    """Return the KMZ filename for *year*.

    Args:
        year: The year the output describes.

    Returns:
        The filename.

    Examples:
        >>> kmz_filename(2025)
        'PeriScribe Fires 2025.kmz'
    """
    return f"PeriScribe Fires {year}.kmz"


def kmz_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the KMZ output for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``maps`` directory.

    Returns:
        The output KMZ path.

    Examples:
        >>> kmz_path(pathlib.Path("data/2025"))
        PosixPath('data/2025/maps/PeriScribe Fires 2025.kmz')
    """
    return (
        year_directory / MAPS_DIRECTORY_NAME / kmz_filename(year_from(year_directory))
    )


def fire_view_folders(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
) -> None:
    """Append every top-level fire view folder that holds fires, given scores.

    The newly discovered, fast-growing, and most-personnel views come first, each
    loading unchecked with its whole tree hidden; the top-fire views follow, with the
    top fires by name loading checked. The status folders load checked only when there
    are no top fires, so a folder is always checked as long as any fire exists.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        scores: The saved score for each fire.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
    """
    wall_clock_time = datetime.datetime.now(datetime.UTC)
    new_notable = peri_scribe.kml.folders.new_notable_fires(
        fires,
        scores,
        wall_clock_time,
    )
    fast_growing_by_acres = peri_scribe.kml.folders.fast_growing_fires_by_acres(
        fires,
        wall_clock_time,
    )
    fast_growing_by_percent = peri_scribe.kml.folders.fast_growing_fires_by_percent(
        fires,
        wall_clock_time,
    )
    most_personnel = peri_scribe.kml.folders.most_personnel_fires(
        fires,
        wall_clock_time,
    )
    score_sorted_fires = peri_scribe.kml.folders.top_fires(fires, scores)
    top_by_name_fires = sorted(
        score_sorted_fires,
        key=lambda fire: fire.name.casefold(),
    )
    if new_notable:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            new_notable,
            peri_scribe.kml.folders.NEW_NOTABLE_FIRES_FOLDER_NAME,
            style_urls,
            ring_style_urls,
            visible=False,
        )
    if fast_growing_by_acres:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            fast_growing_by_acres,
            peri_scribe.kml.folders.FAST_GROWING_FIRES_BY_ACRES_FOLDER_NAME,
            style_urls,
            ring_style_urls,
            visible=False,
        )
    if fast_growing_by_percent:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            fast_growing_by_percent,
            peri_scribe.kml.folders.FAST_GROWING_FIRES_BY_PERCENT_FOLDER_NAME,
            style_urls,
            ring_style_urls,
            visible=False,
        )
    if most_personnel:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            most_personnel,
            peri_scribe.kml.folders.MOST_PERSONNEL_FIRES_FOLDER_NAME,
            style_urls,
            ring_style_urls,
            visible=False,
        )
    if top_by_name_fires:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            top_by_name_fires,
            peri_scribe.kml.folders.TOP_FIRES_BY_NAME_FOLDER_NAME,
            style_urls,
            ring_style_urls,
        )
    if score_sorted_fires:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            score_sorted_fires,
            peri_scribe.kml.folders.TOP_FIRES_BY_SCORE_FOLDER_NAME,
            style_urls,
            ring_style_urls,
            visible=False,
        )
    fire_status_folders(
        writer,
        fires,
        style_urls,
        ring_style_urls,
        top_fires_present=bool(top_by_name_fires),
    )


def fire_status_folders(
    writer: peri_scribe.kml.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    top_fires_present: bool,
) -> None:
    """Append the active and inactive fire folders that hold fires.

    The active fires folder loads checked unless the top fires view is checked instead;
    the inactive fires folder loads checked only when there is no top-fire view and no
    active fire to check. A status folder with no fires is omitted.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        style_urls: The style URL for each template placemark name.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        top_fires_present: Whether the checked top fires by name view was written.
    """
    has_active_fires = any(
        fire.status is peri_scribe.models.FireStatus.ACTIVE for fire in fires
    )
    has_inactive_fires = any(
        fire.status is peri_scribe.models.FireStatus.INACTIVE for fire in fires
    )
    if has_active_fires:
        peri_scribe.kml.folders.status_folder(
            writer,
            fires,
            peri_scribe.models.FireStatus.ACTIVE,
            style_urls,
            ring_style_urls,
            visible=not top_fires_present,
        )
    if has_inactive_fires:
        peri_scribe.kml.folders.status_folder(
            writer,
            fires,
            peri_scribe.models.FireStatus.INACTIVE,
            style_urls,
            ring_style_urls,
            visible=not top_fires_present and not has_active_fires,
        )


def fire_kml(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    scores: peri_scribe.models.FireScores | None = None,
    ring_style_urls: typing.Mapping[str, str] | None = None,
) -> str:
    """Return the KML document string for *fires*.

    The document is named *name* and holds the symbolization styles, the
    progression-ring styles, and a top-level folder, also named *name*. The top-level
    folder holds the fire views as radio options, each created only when it holds fires.
    When scores are supplied the folder begins with the newly discovered, fast growing,
    and most-personnel views, followed by the top-fire views and the active and inactive
    fire folders; without scores it holds the active and inactive fire folders.

    Args:
        fires: The fires to symbolize.
        name: The document's name, conventionally the output filename without its
            extension.
        scores: The saved score for each fire, or None.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color, or None for none.

    Returns:
        The KML document.
    """
    if ring_style_urls is None:
        ring_style_urls = ring_style_urls_for(fires)
    writer = peri_scribe.kml.geometry.KmlWriter()
    writer.parts.append(
        f'<kml xmlns="{peri_scribe.kml.geometry.KML_NAMESPACE}" '
        f'xmlns:gx="{peri_scribe.kml.geometry.GX_NAMESPACE}">'
        "<Document>",
    )
    for style in peri_scribe.kml.styles.symbolization_styles():
        writer.parts.append(str(style))
    for color, style_url in ring_style_urls.items():
        writer.parts.append(
            str(
                peri_scribe.kml.styles.progression_ring_style(
                    style_url.lstrip("#"),
                    color,
                ),
            ),
        )
    writer.parts.append(
        f"<name>{peri_scribe.kml.geometry.escape_text(name)}</name>",
    )

    # The top-level folder holds the fire views as radio options, each created only when
    # it holds fires. Google Earth checks the last radio option that has any visible
    # content, so exactly one folder loads checked: the top fires by name when scores
    # are present, else the active fires, else the inactive fires.
    with writer.folder(name, list_item_type="radioFolder"):
        if scores is not None:
            fire_view_folders(
                writer,
                fires,
                scores,
                peri_scribe.kml.styles.PLACEMARK_STYLE_URLS,
                ring_style_urls,
            )
        else:
            fire_status_folders(
                writer,
                fires,
                peri_scribe.kml.styles.PLACEMARK_STYLE_URLS,
                ring_style_urls,
                top_fires_present=False,
            )
    writer.parts.append("</Document></kml>")
    return writer.text()


def write_kmz(
    path: pathlib.Path,
    kml_text: str,
    images: typing.Mapping[str, bytes] | None = None,
) -> None:
    """Write *kml_text* and *images* as a compressed KMZ file at *path*.

    Args:
        path: The KMZ file to write.
        kml_text: The KML document to compress.
        images: Each plot image's filename and PNG bytes, or None for none.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        path,
        "w",
        compression=KMZ_COMPRESSION,
        compresslevel=KMZ_COMPRESSION_LEVEL,
    ) as archive:
        archive.writestr(KMZ_DOCUMENT_FILENAME, kml_text)
        if images:
            for filename, content in images.items():
                # PNG bytes are already DEFLATE-compressed, so recompressing them is
                # pure waste of time with no size benefit.
                archive.writestr(
                    filename,
                    content,
                    compress_type=zipfile.ZIP_STORED,
                )


def area_qualified_index(
    index: peri_scribe.models.FireIndex,
    perimeters: geopandas.GeoDataFrame,
    points: geopandas.GeoDataFrame,
) -> peri_scribe.models.FireIndex:
    """Return *index* with every fire lacking a qualifying area indication removed.

    A fire stays in the output when any of its computed or reported areas reaches the
    minimum; fires whose every area indication is missing or smaller are dropped, so the
    season's tiny incidents do not clutter the map.

    Args:
        index: The fire index to filter.
        perimeters: The perimeter history layer.
        points: The point history layer.

    Returns:
        The index holding only the qualifying fires.
    """
    qualifying_keys = peri_scribe.kml.selection.fires_with_qualifying_area(
        perimeters,
        points,
        peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
    )
    return peri_scribe.models.FireIndex(
        version=index.version,
        fires=[
            entry
            for entry in index.fires
            if peri_scribe.kml.selection.fire_qualifies(
                peri_scribe.kml.selection.identifiers(entry),
                entry.name,
                qualifying_keys,
            )
        ],
    )


def ring_style_urls_for(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
) -> dict[str, str]:
    """Return the style URL for each progression ring color *fires* use.

    The hottest color is always included because a fire with no dated rings falls back
    to its latest perimeter in that color. Colors are keyed by their ``#RRGGBB`` form,
    so every fire whose rings share a color shares one style.

    Args:
        fires: The fires to symbolize.

    Returns:
        The style URL for each ring color.
    """
    colors = {
        peri_scribe.kml.colormap.color_hex(
            peri_scribe.kml.colormap.TURBO_RAMP[-1],
        ),
    }
    for fire in fires:
        colors.update(
            peri_scribe.kml.colormap.color_hex(rgb)
            for _ring, rgb in peri_scribe.kml.colormap.progression_ring_colors(
                fire.progression_rings,
            )
        )
    return {
        color: f"#{peri_scribe.kml.styles.progression_ring_style_id(color)}"
        for color in sorted(colors)
    }


def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
    """Build and write the KMZ output for *year_directory*.

    The full history GeoPackage is read for geometry, the differential history supplies
    each fire's growth rings, the fire index supplies each fire's name and status, and
    the code-defined styles and placemark style URLs supply the symbolization. Fires
    whose every computed or reported area is missing or under the area minimum are
    excluded from the output. Each fire's plot images and the folder icons are written
    into the archive beside the KML document. The output is written under the year's
    ``maps`` directory.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The path of the written KMZ file.
    """
    index = peri_scribe.fires.index.load_fire_index(year_directory)
    scores = peri_scribe.fires.score_files.load_fire_scores(year_directory)
    history_path = peri_scribe.fires.files.history_geopackage_path(year_directory)
    perimeters = peri_scribe.geo.reading.read_layer(
        history_path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    points = peri_scribe.geo.reading.read_layer(
        history_path,
        peri_scribe.fires.files.POINT_LAYER_NAME,
    )
    differential_path = peri_scribe.fires.differential.differential_geopackage_path(
        year_directory,
    )
    differential_perimeters = peri_scribe.geo.reading.read_layer(
        differential_path,
        peri_scribe.fires.files.PERIMETER_LAYER_NAME,
    )
    fire_count = len(index.fires)
    index = area_qualified_index(index, perimeters, points)
    logger.debug(
        "Excluded fires without a qualifying area",
        fires=len(index.fires),
        excluded_fires=fire_count - len(index.fires),
        minimum_area_in_acres=peri_scribe.kml.selection.MINIMUM_FIRE_AREA_IN_ACRES,
    )
    geometries = peri_scribe.kml.fire_data.fire_geometries(
        index,
        perimeters,
        points,
        differential_perimeters,
        scores=scores,
    )
    images = {
        image.filename: image.content for fire in geometries for image in fire.images
    }
    images[peri_scribe.kml.icons.interior_progression_icon_filename()] = (
        peri_scribe.kml.icons.interior_progression_icon()
    )
    images[peri_scribe.kml.icons.perimeters_icon_filename()] = (
        peri_scribe.kml.icons.perimeters_icon()
    )
    output_path = kmz_path(year_directory)
    write_kmz(
        output_path,
        fire_kml(
            geometries,
            output_path.stem,
            scores or peri_scribe.models.FireScores(version="", fires=[]),
        ),
        images,
    )
    return output_path
