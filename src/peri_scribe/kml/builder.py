"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). Symbolization styles and placemark
style URLs are defined in code; progression-map ring colors are computed from the Turbo
colormap.

Design notes:
[Output serialization](../../../docs/algorithms/output-serialization.md).
"""

from __future__ import annotations

import functools
import io
import pathlib
import typing

import structlog

import document_text.encoding
import kml_io.geometry
import kml_io.kmz
import peri_scribe.fire_updates
import peri_scribe.fires.index
import peri_scribe.fires.score_files
import peri_scribe.kml.colormap
import peri_scribe.kml.fire_data
import peri_scribe.kml.folders
import peri_scribe.kml.icons
import peri_scribe.kml.prepared_inputs
import peri_scribe.kml.styles
import peri_scribe.logging
import peri_scribe.models
import peri_scribe.paths
import peri_scribe.phases
import peri_scribe.preparation
import peri_scribe.presentation.fire_data
import peri_scribe.presentation.index
import peri_scribe.presentation.selection
import peri_scribe.presentation.views
import peri_scribe.publication
import peri_scribe.updates


logger = structlog.get_logger()


FIRIS_SOURCE_URL = (
    "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/"
    "CA_Perimeters_NIFC_FIRIS_public_view/FeatureServer"
)
WFIGS_PERIMETERS_SOURCE_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Interagency_Perimeters_Current/FeatureServer"
)
WFIGS_LOCATIONS_SOURCE_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer"
)
EVACUATIONS_SOURCE_URL = (
    "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/"
    "CA_EVACUATIONS_CalOESHosted_view/FeatureServer"
)
CITIES_SOURCE_URL = (
    "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/"
    "10m-populated-places/"
)
STATE_BOUNDARIES_SOURCE_URL = (
    "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
    "USA_States_Generalized_Boundaries/FeatureServer"
)
BUILDINGS_SOURCE_URL = "https://github.com/microsoft/USBuildingFootprints"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/"

ROOT_DOCUMENT_ATTRIBUTION = document_text.encoding.CData(f"""
    <h3>Data Sources</h3>
    <ul>
        <li>
            <a href="{FIRIS_SOURCE_URL}">
                CAL FIRE/NIFC FIRIS
            </a>
        </li>
        <li>
            <a href="{WFIGS_LOCATIONS_SOURCE_URL}">
                NIFC WFIGS incident locations
            </a>
        </li>
        <li>
            <a href="{WFIGS_PERIMETERS_SOURCE_URL}">
                NIFC WFIGS perimeters
            </a>
        </li>
        <li>
            <a href="{EVACUATIONS_SOURCE_URL}">
                California Governor's Office of Emergency Services evacuation zones
            </a>
        </li>
        <li>
            <a href="{CITIES_SOURCE_URL}">
                Natural Earth populated places
            </a>
        </li>
        <li>
            <a href="{STATE_BOUNDARIES_SOURCE_URL}">
                Esri generalized state boundaries
            </a>
        </li>
        <li>
            <a href="{BUILDINGS_SOURCE_URL}">
                Microsoft USBuildingFootprints
            </a>
        </li>
    </ul>
    <p>
        Microsoft USBuildingFootprints is licensed under the
        <a href="{ODBL_URL}">
            Open Data Commons Open Database License (ODbL)
        </a>.
    </p>
    <p>
        PeriScribe cleans source geometry, builds perimeter histories, and converts
        building footprints to center points (centroids).
    </p>
    <p>
        This data is provided with no warranty. It is intended for educational purposes
        only and not for operational use. Consult the original sources for authoritative
        information.
    </p>
""")


def fire_view_folders(
    writer: kml_io.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    scores: peri_scribe.models.FireScores,
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
) -> None:
    """Append each nonempty fire view in its display order.

    The new, Type 1, fast-growing, and most-personnel views start unchecked, with their
    contents hidden. The top-fire views follow, with top fires by name checked. If there
    are no top fires, a status folder is checked instead. This gives Google Earth a
    visible selection whenever any fires are available.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        scores: The saved score for each fire.
        style_urls: The style URL for each named placemark role.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
    """
    wall_clock_time = peri_scribe.presentation.fire_data.presentation_time()
    new_notable = peri_scribe.presentation.views.new_notable_fires(
        fires,
        scores,
        wall_clock_time,
    )
    type_one = peri_scribe.presentation.views.type_one_fires(fires)
    fast_growing_by_acres = peri_scribe.presentation.views.fast_growing_fires_by_acres(
        fires,
        wall_clock_time,
    )
    fast_growing_by_percent = (
        peri_scribe.presentation.views.fast_growing_fires_by_percent(
            fires,
            wall_clock_time,
        )
    )
    most_personnel = peri_scribe.presentation.views.most_personnel_fires(
        fires,
        wall_clock_time,
    )
    score_sorted_fires = peri_scribe.presentation.views.top_fires(fires, scores)
    top_by_name_fires = sorted(
        score_sorted_fires,
        key=peri_scribe.presentation.fire_data.fire_name_key,
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
    if type_one:
        peri_scribe.kml.folders.top_fires_folder(
            writer,
            type_one,
            peri_scribe.kml.folders.TYPE_1_FIRES_FOLDER_NAME,
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
    writer: kml_io.geometry.KmlWriter,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    style_urls: typing.Mapping[str, str],
    ring_style_urls: typing.Mapping[str, str],
    *,
    top_fires_present: bool,
) -> None:
    """Append the nonempty status folders in active, holding, inactive order.

    The first status folder loads checked unless the top fires view is checked instead.
    Every other folder and its descendants load hidden, so Google Earth selects only
    one radio option. A status folder with no fires is omitted.

    Args:
        writer: The writer to append to.
        fires: Every fire.
        style_urls: The style URL for each named placemark role.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color.
        top_fires_present: Whether the checked top fires by name view was written.
    """
    visible_folder_present = top_fires_present
    for status in (
        peri_scribe.models.FireStatus.ACTIVE,
        peri_scribe.models.FireStatus.HOLDING,
        peri_scribe.models.FireStatus.INACTIVE,
    ):
        if not any(fire.status is status for fire in fires):
            continue
        peri_scribe.kml.folders.status_folder(
            writer,
            fires,
            status,
            style_urls,
            ring_style_urls,
            visible=not visible_folder_present,
        )
        visible_folder_present = True


def fire_kml(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    scores: peri_scribe.models.FireScores | None = None,
    ring_style_urls: typing.Mapping[str, str] | None = None,
) -> str:
    """Provide document text for callers that need an in-memory representation.

    Args:
        fires: The fires to symbolize.
        name: The document name.
        scores: Saved fire scores, or None.
        ring_style_urls: Explicit progression styles, or None to derive them.

    Returns:
        The complete KML text.
    """
    with io.StringIO() as stream:
        write_fire_kml(fires, name, stream, scores, ring_style_urls)
        return stream.getvalue()


def write_fire_kml(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    stream: typing.TextIO,
    scores: peri_scribe.models.FireScores | None = None,
    ring_style_urls: typing.Mapping[str, str] | None = None,
) -> None:
    """Stream the KML document while retaining only shared serialization state.

    The document is named *name* and holds the symbolization styles, the
    progression-ring styles, and a top-level folder, also named *name*. The top-level
    folder holds the fire views as radio options, each created only when it holds fires.
    When scores are supplied the folder begins with the newly discovered, Type 1, fast
    growing, and most-personnel views, followed by the top-fire views and the active,
    holding, and inactive fire folders; without scores it holds the status folders.

    Args:
        stream: The destination for the generated XML.
        fires: The fires to symbolize.
        name: The document's name, conventionally the output filename without its
            extension.
        scores: The saved score for each fire, or None.
        ring_style_urls: The style URL for each progression ring color, keyed by its
            ``#RRGGBB`` color, or None to derive the styles from the fires.
    """
    if ring_style_urls is None:
        ring_style_urls = ring_style_urls_for(fires)
    writer = kml_io.geometry.KmlWriter(stream)
    styles = (
        *peri_scribe.kml.styles.symbolization_styles(),
        *(
            peri_scribe.kml.styles.filled_polygon_style(
                peri_scribe.kml.styles.progression_ring_style_id(color),
                color,
            )
            for color in ring_style_urls
        ),
    )
    # Google Earth checks the last radio option with visible content. When any fires
    # are available, only one view starts checked: top fires by name if it has fires,
    # otherwise active fires, otherwise holding fires, otherwise inactive fires. Empty
    # views are omitted.
    with (
        writer.document(
            name,
            (str(style) for style in styles),
            description=ROOT_DOCUMENT_ATTRIBUTION,
        ),
        writer.folder(name, list_item_type="radioFolder"),
    ):
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


def write_kmz_document(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    name: str,
    stream: typing.TextIO,
    *,
    scores: peri_scribe.models.FireScores,
) -> None:
    """Keep application phase observations outside the archive writer.

    Args:
        fires: The fires to symbolize.
        name: The document name.
        stream: The archive's document stream.
        scores: The saved scores selecting the fire views.
    """
    with peri_scribe.logging.log_phase(peri_scribe.phases.Phase.BUILD_KML):
        write_fire_kml(fires, name, stream, scores)


def ring_style_urls_for(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
) -> dict[str, str]:
    """Return the style URL for each progression ring color used by *fires*.

    A fire without dated rings uses its latest perimeter in the hottest color, so that
    color must always have a style. The ``#RRGGBB`` key lets fires with the same ring
    color share a style.

    Args:
        fires: The fires to symbolize.

    Returns:
        The style URL for each ring color.
    """
    colors = {
        peri_scribe.kml.colormap.color_hex(peri_scribe.kml.colormap.TURBO_RAMP[-1]),
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


@peri_scribe.preparation.cached_year
def create_kmz(
    year_directory: pathlib.Path,
    *,
    publication_inputs: peri_scribe.publication.Collection | None = None,
) -> pathlib.Path:
    """Build and write the KMZ output for *year_directory*.

    The full history GeoPackage is read for geometry, the differential history supplies
    each fire's growth rings, the fire index supplies each fire's name and status, and
    the code-defined styles and placemark style URLs supply the symbolization. A fire
    qualifies when the shared area policy selects a historical estimate at least the
    area minimum, with sparse-record fallbacks when no dated estimate exists. Fires
    without a qualifying estimate are excluded. Each fire's plot images and the folder
    icons are written into the archive beside the KML document. The output is written
    under the year's ``maps`` directory.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.
        publication_inputs: Source inventory frozen after a successful geography stage,
            so the completed KMZ can acknowledge only the inputs it used.

    Returns:
        The path of the written KMZ file.
    """
    index = peri_scribe.fires.index.load_fire_index(year_directory)
    scores = peri_scribe.fires.score_files.load_fire_scores(year_directory)
    prepared = peri_scribe.kml.prepared_inputs.prepare_inputs(year_directory, index)
    layers = prepared.layers
    perimeters = layers.perimeters
    points = layers.points
    differential_perimeters = layers.differential_perimeters
    fire_count = len(index.fires)
    histories = prepared.histories
    index = peri_scribe.presentation.index.area_qualified_index(
        index,
        perimeters,
        points,
        layers.incidents,
        histories=histories,
    )
    logger.debug(
        "Excluded fires without a qualifying area",
        fires=len(index.fires),
        excluded_fires=fire_count - len(index.fires),
        minimum_area=peri_scribe.presentation.selection.MINIMUM_FIRE_AREA,
    )
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.PREPARE_FIRE_GEOMETRIES,
    ):
        geometries = peri_scribe.kml.fire_data.fire_geometries(
            index,
            perimeters,
            points,
            differential_perimeters,
            scores=scores,
            incident_rows=layers.incidents,
            histories=histories,
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
    for color in peri_scribe.kml.styles.OUTLINED_PERIMETER_COLORS:
        images[peri_scribe.kml.icons.outlined_perimeter_icon_filename(color)] = (
            peri_scribe.kml.icons.outlined_perimeter_icon(color)
        )
    output_path = peri_scribe.paths.kmz_path(year_directory)
    published = (
        peri_scribe.publication.published_fires(publication_inputs, perimeters, index)
        if publication_inputs is not None
        else None
    )
    updates = peri_scribe.fire_updates.prepare_updates(
        year_directory,
        geometries,
        scores or peri_scribe.models.FireScores(version="", fires=[]),
    )
    with peri_scribe.logging.log_phase(
        peri_scribe.phases.Phase.SERIALIZE_AND_WRITE_KMZ,
    ):
        kml_io.kmz.write_kmz(
            output_path,
            functools.partial(
                write_kmz_document,
                geometries,
                output_path.stem,
                scores=scores or peri_scribe.models.FireScores(version="", fires=[]),
            ),
            images,
        )
    if publication_inputs is not None and published is not None:
        peri_scribe.publication.commit(
            year_directory,
            output_path,
            publication_inputs,
            published,
        )
    peri_scribe.fire_updates.write_updates(year_directory, updates)
    peri_scribe.updates.write_updates_page(year_directory, fires=geometries)
    return output_path
