"""Downloading archive files and locating geodata inside them."""

from __future__ import annotations

import pathlib
import zipfile
from html.parser import HTMLParser

import requests

import peri_scribe.exceptions
import peri_scribe.sources.downloading


def fetch_page_text(url: str) -> str:
    """Download *url* and return its text.

    Args:
        url: The page's URL.

    Returns:
        The page's text.

    Raises:
        ExternalDataError: If the page cannot be downloaded.
    """
    try:
        response = requests.get(
            url,
            timeout=peri_scribe.sources.downloading.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error
    return response.text


class DownloadLinksParser(HTMLParser):
    """Extract the state-to-URL pairs from a page's "Download links" table.

    GitHub renders the repository's README into the page: each heading is a ``<div
    class="markdown-heading">`` holding the heading element and a permalink anchor, and
    the tables that follow hold the links. The links are collected from the table after
    the "Download links" heading until the next heading starts. The README's copy inside
    the page's embedded-data script is script content, which the parser never treats as
    markup.
    """

    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}
        self.heading_level: str | None = None
        self.heading_text: list[str] = []
        self.collecting = False
        self.anchor_href: str | None = None
        self.anchor_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attribute_map = dict(attrs)
        if tag in {"h1", "h2", "h3"}:
            self.heading_level = tag
            self.heading_text = []
        elif tag == "a":
            self.anchor_href = attribute_map.get("href")
            self.anchor_text = []
        elif (
            tag == "div"
            and "markdown-heading" in (attribute_map.get("class") or "").split()
        ):
            # A new README heading ends the previous section's link table.
            self.collecting = False

    def handle_data(self, data: str) -> None:
        if self.heading_level is not None:
            self.heading_text.append(data)
        elif self.anchor_href is not None:
            self.anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"} and tag == self.heading_level:
            heading = "".join(self.heading_text).strip().lower()
            if heading in {"download links", "downloads links"}:
                self.collecting = True
            self.heading_level = None
            self.heading_text = []
        elif tag == "a":
            if self.collecting:
                label = "".join(self.anchor_text).strip()
                href = self.anchor_href
                if label and href is not None and href.startswith("http"):
                    self.links[label] = href
            self.anchor_href = None
            self.anchor_text = []


def download_links(html_text: str) -> dict[str, str]:
    """Return the state-to-URL pairs from a page's "Download links" table.

    Args:
        html_text: The page's HTML.

    Returns:
        The mapping from state name to archive URL, in table order.

    Examples:
        >>> download_links(
        ...     '<div class="markdown-heading"><h2>Download links</h2></div>'
        ...     '<a href="https://example.com/ca.zip">California</a>'
        ... )
        {'California': 'https://example.com/ca.zip'}
    """
    parser = DownloadLinksParser()
    parser.feed(html_text)
    return parser.links


def download_archive(url: str, archive_path: pathlib.Path) -> None:
    """Download *url* to *archive_path*.

    Args:
        url: The archive's URL.
        archive_path: Where to store the downloaded archive.

    Raises:
        ExternalDataError: If the download fails.
    """
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=peri_scribe.sources.downloading.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with archive_path.open("wb") as file:
            for chunk in response.iter_content(
                chunk_size=peri_scribe.sources.downloading.DOWNLOAD_CHUNK_SIZE,
            ):
                file.write(chunk)
    except requests.exceptions.RequestException as error:
        message = f"Failed to download {url}: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def extract_archive(
    archive_path: pathlib.Path,
    extraction_directory: pathlib.Path,
) -> None:
    """Extract *archive_path* into *extraction_directory*.

    Args:
        archive_path: The zip archive to extract.
        extraction_directory: The directory to extract into.

    Raises:
        ExternalDataError: If the archive is not a zip file.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extraction_directory)
    except zipfile.BadZipFile as error:
        message = f"{archive_path} is not a zip file: {error}"
        raise peri_scribe.exceptions.ExternalDataError(message) from error


def find_geodata_path(
    directory: pathlib.Path,
    suffix: str,
) -> pathlib.Path:
    """Return the first vector data path ending in *suffix* under *directory*.

    The suffix names either a data file (``.geojson``, ``.shp``) or a file geodatabase
    directory (``.gdb``), so both files and directories are matched.

    Args:
        directory: The extracted archive directory.
        suffix: The suffix that names the vector data (``.geojson``, ``.shp``,
            ``.gdb``).

    Returns:
        The vector data path.

    Raises:
        ExternalDataError: If no matching path is found.
    """
    matches = sorted(
        path
        for path in directory.rglob(f"*{suffix}")
        if path.is_file() or path.is_dir()
    )
    if not matches:
        message = f"No {suffix} data found under {directory}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return matches[0]
