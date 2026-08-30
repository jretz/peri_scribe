"""Test helpers for external source tests."""

from __future__ import annotations

import dataclasses
import io
import pathlib
import tempfile
import typing
import zipfile

import geopandas
import shapely.geometry

import peri_scribe.sources.external_sources


class FakeResponse:
    """Stand-in for a requests response with a fixed body."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        """No-op; the response is treated as successful."""

    @property
    def text(self) -> str:
        """The response body decoded as text."""
        return self.body.decode("utf-8")

    def iter_content(self, chunk_size: int) -> typing.Iterator[bytes]:
        """Yield the body in chunks of *chunk_size* bytes.

        Args:
            chunk_size: The number of bytes per chunk.

        Yields:
            The body chunks.
        """
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


def buildings_page_html(links: dict[str, str]) -> str:
    """Render a GitHub-style page whose "Download links" table holds *links*.

    The page mirrors the README rendering GitHub serves for the repository page: a
    "Download links" heading followed by a table whose rows link each state to its
    archive, bracketed by other headings and a link so the parser must select the
    right table.

    Args:
        links: The state-to-archive-URL pairs the table should hold.

    Returns:
        The page's HTML.
    """
    rows = "\n".join(
        (
            f'<tr><td align="left"><a href="{url}" rel="nofollow">'
            f"{state}</a></td>"
            '<td align="center">1</td><td align="right">1 MiB</td></tr>'
        )
        for state, url in links.items()
    )
    heading = (
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Download links</h2>'
        '<a id="user-content-download-links" class="anchor" '
        'href="#download-links"></a></div>'
    )
    table = (
        "<markdown-accessiblity-table><table><thead><tr>"
        '<th align="left">State or district</th>'
        '<th align="center">Number of Buildings</th>'
        '<th align="right">Unzipped size</th>'
        "</tr></thead><tbody>"
        f"{rows}</tbody></table></markdown-accessiblity-table>"
    )
    return (
        '<!DOCTYPE html><html lang="en"><body>'
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Introduction</h2>'
        '<a id="user-content-introduction" class="anchor" '
        'href="#introduction"></a></div>'
        '<p dir="auto">See the <a href="https://example.com/other">region</a>.</p>'
        f"{heading}{table}"
        '<div class="markdown-heading" dir="auto"><h2 tabindex="-1" '
        'class="heading-element" dir="auto">Contributing</h2>'
        '<a id="user-content-contributing" class="anchor" '
        'href="#contributing"></a></div>'
        "</body></html>"
    )


def sample_arcgis_dataframe() -> geopandas.GeoDataFrame:
    """Return a small WGS84 dataframe for an ArcGIS fetch test.

    Returns:
        Two point features with OBJECTID attributes in WGS84.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[
            shapely.geometry.Point(1.0, 2.0),
            shapely.geometry.Point(3.0, 4.0),
        ],
        crs="EPSG:4326",
    )


def archive_zip_bytes(
    *,
    filename: str,
    dataframe: geopandas.GeoDataFrame,
    driver: str,
) -> bytes:
    """Build an in-memory zip holding *dataframe* written with *driver*.

    Args:
        filename: The output filename the driver writes, and the prefix matching the
            files the zip holds.
        dataframe: The data to archive.
        driver: The OGR driver to write the data with.

    Returns:
        The zip archive's bytes.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / filename
        dataframe.to_file(path, driver=driver)
        stem = path.stem
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for file_path in sorted(path.parent.iterdir()):
                if file_path.stem == stem:
                    archive.writestr(file_path.name, file_path.read_bytes())
        return buffer.getvalue()


def building_dataframe() -> geopandas.GeoDataFrame:
    """Return a small footprint dataframe for a conversion test.

    Returns:
        Two building footprint polygons with OBJECTID attributes.
    """
    return geopandas.GeoDataFrame(
        {"OBJECTID": [1, 2]},
        geometry=[
            shapely.geometry.box(0.0, 0.0, 2.0, 2.0),
            shapely.geometry.box(10.0, 10.0, 12.0, 12.0),
        ],
        crs="EPSG:4326",
    )


def per_state_template_source() -> peri_scribe.sources.external_sources.ExternalSource:
    """Return the buildings source without its page, using a URL template.

    The real buildings source reads its per-state links from the repository page;
    the generic download path (a ``{state}`` URL template) is exercised with this
    source so that download and conversion failures can be tested directly.

    Returns:
        A per-state download source named after the buildings source.
    """
    return dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=("California",),
        state_urls=None,
        url="https://example.com/legacy/{state}.geojson.zip",
        stream=False,
    )


def single_archive_source() -> peri_scribe.sources.external_sources.ExternalSource:
    """Return the buildings source as a single archive instead of per state.

    The generic single-archive download path is exercised with this source so that
    the skip-when-present behavior can be tested without the per-state machinery.

    Returns:
        A single-archive download source named after the buildings source.
    """
    return dataclasses.replace(
        peri_scribe.sources.external_sources.BUILDINGS_SOURCE,
        states=(),
        combine=False,
        state_urls=None,
        url="https://example.com/buildings.geojson.zip",
    )
