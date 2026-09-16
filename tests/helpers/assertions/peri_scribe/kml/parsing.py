"""Compare parsing behavior through reusable assertions."""

from __future__ import annotations

import typing

import tests.helpers.peri_scribe.kml.parsing


if typing.TYPE_CHECKING:
    import xml.etree.ElementTree as ET


def assert_tree_invisible(container: ET.Element) -> None:
    """Assert *container* and every feature beneath it is unchecked.

    Args:
        container: The folder whose whole tree must be invisible.
    """
    for feature in container.iter():
        if feature.tag not in {
            tests.helpers.peri_scribe.kml.parsing.kml_tag("Folder"),
            tests.helpers.peri_scribe.kml.parsing.kml_tag("Placemark"),
            tests.helpers.peri_scribe.kml.parsing.gx_tag("Tour"),
        }:
            continue
        # Tour update instructions reuse Placemark and Folder tags but carry a targetId
        # rather than being real features, so they are not part of the tree whose
        # visibility is asserted here.
        if feature.get("targetId") is not None:
            continue
        assert tests.helpers.peri_scribe.kml.parsing.visibility(feature) == 0, (
            feature.findtext(tests.helpers.peri_scribe.kml.parsing.kml_tag("name"))
        )


def assert_tree_visible(container: ET.Element) -> None:
    """Assert *container* and every feature beneath it is checked.

    Args:
        container: The folder whose whole tree must be visible.
    """
    for feature in container.iter():
        if feature.tag not in {
            tests.helpers.peri_scribe.kml.parsing.kml_tag("Folder"),
            tests.helpers.peri_scribe.kml.parsing.kml_tag("Placemark"),
            tests.helpers.peri_scribe.kml.parsing.gx_tag("Tour"),
        }:
            continue
        # Tour update instructions reuse Placemark and Folder tags but carry a targetId
        # rather than being real features, so they are not part of the tree whose
        # visibility is asserted here.
        if feature.get("targetId") is not None:
            continue
        assert tests.helpers.peri_scribe.kml.parsing.visibility(feature) is None, (
            feature.findtext(tests.helpers.peri_scribe.kml.parsing.kml_tag("name"))
        )
