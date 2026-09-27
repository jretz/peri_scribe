"""Inspect complete KMZ resources, feature ownership, and animated target references."""

from __future__ import annotations

import datetime
import decimal
import functools
import pathlib
import re
import typing
import zipfile

import defusedxml.ElementTree as DefusedElementTree
import shapely
import time_machine

import kml_io.kmz
import peri_scribe.kml.builder
import peri_scribe.kml.fire_data
import peri_scribe.kml.icons
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import peri_scribe.kml.styles
import peri_scribe.models
import peri_scribe.perimeters.progression
import peri_scribe.presentation.descriptions
import peri_scribe.presentation.perimeters
import svg_charts.models
import tests.formal.helpers.oracle
import tests.formal.helpers.output_references
import tests.formal.helpers.ranked_views
import tests.helpers.peri_scribe.kml.parsing
from measurement_units import units


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


KML = "{http://www.opengis.net/kml/2.2}"
GX = "{http://www.google.com/kml/ext/2.2}"


def geometries(counts: tuple[int, ...]) -> list[peri_scribe.kml.fire_data.FireGeometry]:
    """Create distinct source-owned charts and histories with colliding filename bases.

    Args:
        counts: Number of dated growth rings per fire; zero uses undated fallback.

    Returns:
        Actual rendered SVG images attached to their owning fire facts.
    """
    result = []
    used: set[str] = set()
    for owner, (identifier, count) in enumerate(
        zip(("X!", "X?", "x-2", "!!!"), counts, strict=True),
    ):
        prefix = peri_scribe.kml.fire_data.unique_filename_prefix(
            identifier,
            "Same",
            frozenset(used),
        )
        used.add(prefix)
        plot = peri_scribe.kml.plot_data.FirePlot(
            filename_suffix="area",
            y_axis_label="Acres",
            series=(
                svg_charts.models.PlotSeries(
                    label=f"owner-{owner}",
                    points=tuple(
                        svg_charts.models.SeriesPoint(
                            observation_time=tests.formal.helpers.ranked_views.ORIGIN
                            + datetime.timedelta(days=index),
                            value=100 * (owner + 1) + index,
                        )
                        for index in range(2)
                    ),
                ),
            ),
        )
        images = peri_scribe.kml.plot_rendering.plot_image_bundles((
            (prefix, (plot,)),
        ))[0]
        perimeters = tuple(
            peri_scribe.presentation.perimeters.Perimeter(
                geometry=shapely.box(owner, 0, owner + 0.01 * (index + 1), 0.01),
                observation_time=(
                    tests.formal.helpers.ranked_views.ORIGIN
                    + datetime.timedelta(days=index)
                    if count
                    else None
                ),
                area=100 * (index + 1) * units.acres,
            )
            for index in range(max(count, 1))
        )
        result.append(
            peri_scribe.kml.fire_data.FireGeometry(
                name="Same",
                identifiers=frozenset({identifier}),
                status=(
                    peri_scribe.models.FireStatus.ACTIVE
                    if owner % 2
                    else peri_scribe.models.FireStatus.INACTIVE
                ),
                point=shapely.Point(owner, 0),
                perimeters=perimeters,
                progression_rings=tuple(
                    peri_scribe.perimeters.progression.Ring(
                        geometry=perimeter.geometry,
                        observation_time=perimeter.observation_time,
                    )
                    for perimeter in perimeters
                    if count
                ),
                images=images,
                description=peri_scribe.presentation.descriptions.FireDescription(
                    identifier=f"owner-{owner}",
                    discovery_time=tests.formal.helpers.ranked_views.ORIGIN,
                    observation_time=tests.formal.helpers.ranked_views.ORIGIN,
                    total_personnel=10 + owner,
                ),
                type_one=owner % 2 == 1,
            ),
        )
    return result


def archive_images(
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
) -> dict[str, bytes]:
    """Assemble complete plot and icon payloads used by the real archive writer.

    Args:
        fires: Rendered fire imagery.

    Returns:
        Filename-to-content registry whose ownership is checked after serialization.
    """
    images = {image.filename: image.content for fire in fires for image in fire.images}
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
    return images


def check_tour(folder: ET.Element, count: int) -> None:
    """Compare actual serialized target registries and every animation visibility step.

    Args:
        folder: One concrete fire occurrence inside a view.
        count: The source history's expected visible ring count.
    """
    tour = folder.find(f"{GX}Tour")
    assert tour is not None
    updates = tour.findall(f".//{GX}AnimatedUpdate")
    rings = folder.findall(f"{KML}Folder/{KML}Placemark[@id]")
    identifiers = [ring.attrib["id"] for ring in rings]
    assert len(identifiers) == count
    assert len(updates) == count
    match = re.fullmatch(r"progression-ring-(\d+)-(\d+)", identifiers[0])
    assert match is not None
    occurrence = int(match[1])
    expected = tests.formal.helpers.oracle.evaluate(
        [f"rings {occurrence} | {count}"]
        + [f"reveal {step} | {count}" for step in range(count)],
        executable="oracleOutputs",
    )
    pairs = expected[0]
    targets = [
        f"progression-ring-{pairs[index]}-{pairs[index + 1]}"
        for index in range(0, len(pairs), 2)
    ]
    assert identifiers == list(reversed(targets))
    for update, visibility in zip(updates, expected[1:], strict=True):
        actual = tests.helpers.peri_scribe.kml.parsing.update_visibility_by_target(
            update,
        )
        assert actual == dict(zip(targets, visibility, strict=True))
    waits = tour.findall(f".//{GX}duration")
    assert all(float(wait.text or "-1") >= 0 for wait in waits)


def check_folder(
    folder: ET.Element,
    fires: list[peri_scribe.kml.fire_data.FireGeometry],
    counts: tuple[int, ...],
) -> None:
    """Bind balloon/chart/tour references to the owner of the serialized point geometry.

    Args:
        folder: One fire occurrence with a direct point placemark.
        fires: Independent source records used to write the artifact.
        counts: Expected dated-ring counts, with undated fallback at zero.
    """
    point = folder.find(f"{KML}Placemark/{KML}Point/{KML}coordinates")
    assert point is not None
    assert point.text is not None
    owner = int(float(point.text.split(",")[0]))
    assert decimal.Decimal(point.text.split(",")[0]) == owner
    assert 0 <= owner < len(fires)
    expected = fires[owner]
    references = []
    for description in folder.findall(f".//{KML}description"):
        assert description.text is not None
        assert f"owner-{owner}" in description.text
        images = re.findall(r'<img src="([^"]+)"', description.text)
        assert images == [image.filename for image in expected.images]
        references.extend((image, owner) for image in images)
    assert references
    resources = [
        (image.filename, index)
        for index, fire in enumerate(fires)
        for image in fire.images
    ]
    assert tests.formal.helpers.output_references.closure(resources, references)
    check_tour(folder, max(counts[owner], 1))


def check_archive(directory: pathlib.Path, counts: tuple[int, ...]) -> None:
    """Open real ZIP/XML and inspect all payloads and cross-feature references.

    Args:
        directory: Isolated output location.
        counts: Independent source ring counts for the four colliding-name fires.
    """
    fires = geometries(counts)
    scores = peri_scribe.models.FireScores(
        version="formal",
        fires=[
            peri_scribe.models.FireScoreEntry(
                name=fire.name,
                identifier=next(iter(fire.identifiers)),
                score=100 - index,
                explanation="",
            )
            for index, fire in enumerate(fires)
        ],
    )
    images = archive_images(fires)
    path = directory / "output.kmz"
    with time_machine.travel(tests.formal.helpers.ranked_views.ORIGIN, tick=False):
        kml_io.kmz.write_kmz(
            path,
            functools.partial(
                peri_scribe.kml.builder.write_fire_kml,
                fires,
                "Reference contract",
                scores=scores,
            ),
            images,
        )
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert set(names) == {"doc.kml", *images}
        for filename, payload in images.items():
            assert archive.read(filename) == payload
        document = DefusedElementTree.fromstring(archive.read("doc.kml"))
    identifiers = [item.attrib["id"] for item in document.iter() if "id" in item.attrib]
    assert len(identifiers) == len(set(identifiers))
    styles = {item.attrib["id"] for item in document.findall(f".//{KML}Style[@id]")}
    urls = [item.text for item in document.findall(f".//{KML}styleUrl")]
    assert urls
    assert all(url and url.startswith("#") and url[1:] in styles for url in urls)
    hrefs = [item.text for item in document.findall(f".//{KML}href")]
    assert all(
        href in names or href == peri_scribe.kml.styles.POINT_ICON_URL for href in hrefs
    )
    fire_folders = [
        folder
        for folder in document.findall(f".//{KML}Folder")
        if folder.find(f"{KML}Placemark/{KML}Point") is not None
    ]
    assert len(fire_folders) > len(fires)
    for folder in fire_folders:
        check_folder(folder, fires, counts)
