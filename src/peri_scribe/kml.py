"""Building the KML output for a year's fires.

The output is a compressed KML document (a KMZ file). The symbolization comes from the
KML template file: its styles are copied into the output, and each fire's placemarks
reuse the style URLs the template assigns to the corresponding placemarks.
"""

from __future__ import annotations

import pathlib
import typing
import zipfile

import simplekml

import peri_scribe.fire_differential
import peri_scribe.fire_history
import peri_scribe.fire_index
import peri_scribe.geo_package
import peri_scribe.kml_fire_data
import peri_scribe.kml_folders
import peri_scribe.kml_icons
import peri_scribe.kml_template
import peri_scribe.kml_template_reader
import peri_scribe.models


MAPS_DIRECTORY_NAME = "maps"

KMZ_DOCUMENT_FILENAME = "doc.kml"

# DEFLATE is the compression Google Earth expects inside a KMZ, and level 9 is the
# highest compression level it offers.
KMZ_COMPRESSION = zipfile.ZIP_DEFLATED
KMZ_COMPRESSION_LEVEL = 9


def year_from(year_directory: pathlib.Path) -> int:
    """Return the year named by *year_directory*.

    Args:
        year_directory: The year directory, whose name is the year.

    Returns:
        The year as an integer.
    """
    return int(year_directory.name)


def kmz_filename(year: int) -> str:
    """Return the KMZ filename for *year*.

    Args:
        year: The year the output describes.

    Returns:
        The filename.
    """
    return f"PeriScribe Fires {year}.kmz"


def kmz_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the path of the KMZ output for *year_directory*.

    Args:
        year_directory: The year directory that holds the ``maps`` directory.

    Returns:
        The output KMZ path.
    """
    return (
        year_directory / MAPS_DIRECTORY_NAME / kmz_filename(year_from(year_directory))
    )


def fire_kml(
    fires: list[peri_scribe.kml_fire_data.FireGeometry],
    template: peri_scribe.kml_template_reader.Template,
    name: str,
) -> str:
    """Return the KML document string for *fires*.

    The document is named *name* and holds the template's styles and a top-level folder,
    also named *name*, that holds one folder each for active and inactive fires.

    Args:
        fires: The fires to symbolize.
        template: The template supplying styles and style URLs.
        name: The document's name, conventionally the output filename without
            its extension.

    Returns:
        The KML document.
    """
    kml = simplekml.Kml(name=name)
    document = kml.document

    for style in template.styles:
        document.styles.append(style)

    # The top-level folder holds the status folders as radio options, so they display as
    # radio buttons in Google Earth's Places panel.
    top_level = document.newfolder(name=name)
    peri_scribe.kml_folders.set_radio_folder(top_level)
    peri_scribe.kml_folders.status_folder(
        top_level,
        fires,
        peri_scribe.models.FireStatus.ACTIVE,
        template.style_urls,
    )
    peri_scribe.kml_folders.status_folder(
        top_level,
        fires,
        peri_scribe.models.FireStatus.INACTIVE,
        template.style_urls,
    )
    return kml.kml()


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
                archive.writestr(filename, content)


def create_kmz(year_directory: pathlib.Path) -> pathlib.Path:
    """Build and write the KMZ output for *year_directory*.

    The full history GeoPackage is read for geometry, the differential history supplies
    each fire's growth rings, the fire index supplies each fire's name and status, and
    the KML template file supplies the symbolization. Each fire's plot images and the
    folder icons are written into the archive beside the KML document. The output is
    written under the year's ``maps`` directory.

    Args:
        year_directory: The year directory that holds the ``derived`` directory.

    Returns:
        The path of the written KMZ file.
    """
    index = peri_scribe.fire_index.load_fire_index(year_directory)
    history_path = peri_scribe.fire_history.history_geopackage_path(year_directory)
    perimeters = peri_scribe.geo_package.read_layer(
        history_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    points = peri_scribe.geo_package.read_layer(
        history_path,
        peri_scribe.fire_history.POINT_LAYER_NAME,
    )
    differential_path = peri_scribe.fire_differential.differential_geopackage_path(
        year_directory,
    )
    differential_perimeters = peri_scribe.geo_package.read_layer(
        differential_path,
        peri_scribe.fire_history.PERIMETER_LAYER_NAME,
    )
    template = peri_scribe.kml_template_reader.read_template(
        peri_scribe.kml_template.template_path(),
    )
    geometries = peri_scribe.kml_fire_data.fire_geometries(
        index,
        perimeters,
        points,
        differential_perimeters,
    )
    images = {
        image.filename: image.content for fire in geometries for image in fire.images
    }
    images.update(peri_scribe.kml_icons.progression_icons(template))
    images[peri_scribe.kml_icons.interior_icon_filename()] = (
        peri_scribe.kml_icons.interior_icon(template)
    )
    images[peri_scribe.kml_icons.perimeters_icon_filename()] = (
        peri_scribe.kml_icons.perimeters_icon(template)
    )
    output_path = kmz_path(year_directory)
    write_kmz(
        output_path,
        fire_kml(geometries, template, output_path.stem),
        images,
    )
    return output_path
