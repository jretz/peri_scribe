"""Parsing the KML symbolization template.

The template is a local, user-edited file rather than untrusted input, so the stdlib
XML parser needs no defusedxml hardening. This module reads its styles and placemark
style URLs for reuse when symbolizing real fire geography.
"""

from __future__ import annotations

import dataclasses
import pathlib

# The template is a local, user-edited file rather than untrusted input, so the
# stdlib XML parser needs no defusedxml hardening.
import xml.etree.ElementTree as ET  # ruff: ignore[suspicious-xml-etree-import]

import peri_scribe.kml_template


KML_NAMESPACE = "http://www.opengis.net/kml/2.2"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Template:
    """The parsed KML template's styles and placemark style URLs."""

    styles: tuple[peri_scribe.kml_template.Style, ...]
    style_urls: dict[str, str]


def kml_tag(name: str) -> str:
    """Return the namespaced element tag for *name*.

    Args:
        name: The KML element name.

    Returns:
        The tag ElementTree uses for the element.
    """
    return f"{{{KML_NAMESPACE}}}{name}"


def style_from(element: ET.Element) -> peri_scribe.kml_template.Style:
    """Return the template style that *element* defines.

    The template's styles are icon, line, and polygon styles, so those are the
    sub-styles read from *element*.

    Args:
        element: The parsed ``Style`` element.

    Returns:
        The style, holding the sub-styles *element* defines.

    Raises:
        ValueError: When *element* has no id attribute.
    """
    style_id = element.get("id")
    if style_id is None:
        message = "KML Style element has no id attribute"
        raise ValueError(message)
    style = peri_scribe.kml_template.Style(style_id)
    icon_style = element.find(kml_tag("IconStyle"))
    if icon_style is not None:
        icon_href = icon_style.findtext(
            f"{kml_tag('Icon')}/{kml_tag('href')}",
        )
        if icon_href is not None:
            style.iconstyle.icon.href = icon_href
    line_style = element.find(kml_tag("LineStyle"))
    if line_style is not None:
        line_color = line_style.findtext(kml_tag("color"))
        if line_color is not None:
            style.linestyle.color = line_color
        line_width = line_style.findtext(kml_tag("width"))
        if line_width is not None:
            style.linestyle.width = float(line_width)
    poly_style = element.find(kml_tag("PolyStyle"))
    if poly_style is not None:
        poly_color = poly_style.findtext(kml_tag("color"))
        if poly_color is not None:
            style.polystyle.color = poly_color
        fill = poly_style.findtext(kml_tag("fill"))
        if fill is not None:
            style.polystyle.fill = int(fill)
        outline = poly_style.findtext(kml_tag("outline"))
        if outline is not None:
            style.polystyle.outline = int(outline)
    return style


def placemark_style_urls(document: ET.Element) -> dict[str, str]:
    """Return each template placemark's style URL, keyed by name.

    Args:
        document: The parsed template document element.

    Returns:
        The style URL for each placemark name.
    """
    urls: dict[str, str] = {}
    collect_placemark_style_urls(document, urls)
    return urls


def collect_placemark_style_urls(
    element: ET.Element,
    urls: dict[str, str],
) -> None:
    """Record each named placemark's style URL into *urls*.

    Args:
        element: The element to search, descending into folders.
        urls: The mapping being built.
    """
    for child in element:
        if child.tag == kml_tag("Folder"):
            collect_placemark_style_urls(child, urls)
        elif child.tag == kml_tag("Placemark"):
            name = child.findtext(kml_tag("name"))
            style_url = child.findtext(kml_tag("styleUrl"))
            if name is not None and style_url is not None:
                urls[name] = style_url


def template_from(kml_text: str) -> Template:
    """Parse *kml_text* into the template's styles and style URLs.

    Args:
        kml_text: The KML template document.

    Returns:
        The template.

    Raises:
        ValueError: When *kml_text* has no Document element.
    """
    root = ET.fromstring(kml_text)  # ruff: ignore[suspicious-xml-element-tree-usage]
    document = root.find(kml_tag("Document"))
    if document is None:
        message = "KML template has no Document element"
        raise ValueError(message)
    return Template(
        styles=tuple(
            style_from(style) for style in document if style.tag == kml_tag("Style")
        ),
        style_urls=placemark_style_urls(document),
    )


def read_template(path: pathlib.Path) -> Template:
    """Read and parse the KML template at *path*.

    Args:
        path: The KML template file.

    Returns:
        The template.
    """
    return template_from(path.read_text(encoding="utf-8"))
