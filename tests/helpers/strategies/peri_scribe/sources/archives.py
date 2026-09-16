"""Generate archives examples with constrained domains."""

from __future__ import annotations

import dataclasses
import html

import hypothesis.strategies

import tests.helpers.factories.peri_scribe.sources.archives


@dataclasses.dataclass(frozen=True, kw_only=True)
class DownloadPage:
    """Keep expected downloads independent of the markup that presents them."""

    html_text: str
    links: dict[str, str]


@hypothesis.strategies.composite
def download_pages(draw: hypothesis.strategies.DrawFn) -> DownloadPage:
    """Exercise section boundaries, nested text, and HTML entities in download tables.

    Args:
        draw: The current example's strategy sampler.

    Returns:
        A rendered page and the downloads belonging to its selected section.
    """
    entries = draw(
        hypothesis.strategies.dictionaries(
            hypothesis.strategies.from_regex(
                r"[A-Za-z][A-Za-z &<>\"]{0,20}",
                fullmatch=True,
            ).map(str.strip),
            hypothesis.strategies.integers(0, 100),
            max_size=8,
        ),
    )
    links = {
        label: f"https://example.test/{number}.zip?version=1&kind=footprints"
        for label, number in entries.items()
    }
    heading_text = draw(
        hypothesis.strategies.sampled_from([
            "Download links",
            "Downloads links",
            " DOWNLOAD LINKS ",
        ]),
    )
    level = draw(hypothesis.strategies.integers(1, 3))
    wrapped = draw(hypothesis.strategies.booleans())
    rows = "".join(
        f'<tr><td><a href="{html.escape(url)}"><span>{html.escape(label)}</span></a>'
        "</td></tr>"
        for label, url in links.items()
    )
    return DownloadPage(
        links=links,
        html_text=(
            tests.helpers.factories.peri_scribe.sources.archives.section_heading(
                "Introduction",
                level,
                wrapped=wrapped,
            )
            + '<a href="https://example.test/before.zip">Outside/Before</a>'
            + tests.helpers.factories.peri_scribe.sources.archives.section_heading(
                heading_text,
                level,
                wrapped=wrapped,
            )
            + f"<table>{rows}</table>"
            + tests.helpers.factories.peri_scribe.sources.archives.section_heading(
                "Contributing",
                level,
                wrapped=wrapped,
            )
            + '<a href="https://example.test/after.zip">Outside/After</a>'
        ),
    )
