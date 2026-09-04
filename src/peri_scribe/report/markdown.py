"""Rendering a gathered fire report as Markdown."""

from __future__ import annotations

import datetime
import pathlib
import re
import typing

import peri_scribe.kml.descriptions
import peri_scribe.kml.folders
import peri_scribe.report.gathering


REPORTS_DIRECTORY_NAME = "reports"

# The fast-growth window, expressed in whole hours for the report's prose.
FAST_GROWTH_WINDOW_IN_HOURS = int(
    peri_scribe.kml.folders.FAST_GROWTH_LOOKBACK / datetime.timedelta(hours=1),
)

# The smallest growth percentage the report's formatter shows without rounding to 0%,
# so a fire's details claim it grew only when that growth is visible.
MINIMUM_DISPLAYED_GROWTH_IN_PERCENT = 0.1


def markdown_report_path(year_directory: pathlib.Path) -> pathlib.Path:
    """Return the Markdown report path for *year_directory*.

    Args:
        year_directory: The year directory, whose name is the year.

    Returns:
        The report's output path.

    Examples:
        >>> markdown_report_path(pathlib.Path("data/2026"))
        PosixPath('data/2026/reports/PeriScribe Fires 2026.md')
    """
    year = int(year_directory.name)
    return year_directory / REPORTS_DIRECTORY_NAME / f"PeriScribe Fires {year}.md"


def discovery_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s discovery fact, or None when its discovery time is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The discovery phrase, or None.
    """
    if entry.discovery_time is None:
        return None
    return (
        "discovered "
        f"{peri_scribe.kml.descriptions.format_pacific_time(entry.discovery_time)}"
    )


def growth_in_acres_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s acreage-growth fact, or None when growth is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The growth phrase, or None.
    """
    if entry.growth_in_acres is None:
        return None
    return (
        "+"
        f"{peri_scribe.kml.descriptions.format_in_acres(entry.growth_in_acres)} "
        f"in {FAST_GROWTH_WINDOW_IN_HOURS} hours"
    )


def growth_in_percent_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s percent-growth fact, or None when growth is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The growth phrase, or None.
    """
    if entry.growth_in_percent is None:
        return None
    return (
        "+"
        f"{peri_scribe.kml.descriptions.format_in_percent(entry.growth_in_percent)} "
        f"in {FAST_GROWTH_WINDOW_IN_HOURS} hours"
    )


def area_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s area fact, or None when its area is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The area phrase, or None.
    """
    return peri_scribe.kml.descriptions.format_in_acres(entry.area_in_acres)


def containment_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s containment fact, or None when containment is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The containment phrase, like ``50% contained``, or None.
    """
    percent_text = peri_scribe.kml.descriptions.format_in_percent(
        entry.percent_contained,
    )
    if percent_text is None:
        return None
    return f"{percent_text} contained"


def fire_heading(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str:
    """Return *entry*'s details heading text.

    The heading carries the fire's name, followed by its identifier in parentheses when
    one is known, matching the label the fire's list bullets show.

    Args:
        entry: The fire to describe.

    Returns:
        The heading text, without its Markdown ``###`` prefix.
    """
    heading = entry.name
    if entry.identifier is not None:
        heading += f" ({entry.identifier})"
    return heading


def heading_anchor(heading: str) -> str:
    """Return the anchor a Markdown renderer assigns to *heading*.

    GitHub-style anchors keep letters, digits, hyphens, and underscores, replace runs of
    spaces with hyphens, and lowercase the result, so list bullets can link to a
    fire's details heading.

    Args:
        heading: The heading text, without its Markdown prefix.

    Returns:
        The heading's anchor.
    """
    slug = heading.casefold()
    slug = re.sub(r"[^\w \-]+", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def fire_bullet(
    entry: peri_scribe.report.gathering.FireReportEntry,
    *,
    primary_fact: str | None = None,
    anchor: str | None = None,
) -> str:
    """Return one fire as a Markdown bullet.

    The fire's name is followed by its identifier when one is known, and the whole label
    links to the fire's details section when *anchor* is given. The bullet's facts open
    with *primary_fact* when one is given, then carry the fire's latest area; a fact
    that is unknown is left out rather than shown as a placeholder.

    Args:
        entry: The fire to describe.
        primary_fact: The section-specific fact to lead with, or None.
        anchor: The details heading's anchor to link the label to, or None.

    Returns:
        The bullet line.
    """
    label = f"**{entry.name}**"
    if entry.identifier is not None:
        label += f" ({entry.identifier})"
    if anchor is not None:
        label = f"[{label}](#{anchor})"
    facts: list[str] = []
    if primary_fact is not None:
        facts.append(primary_fact)
    area_text = area_fact(entry)
    if area_text is not None:
        facts.append(area_text)
    if facts:
        return f"- {label} — " + ", ".join(facts)
    return f"- {label}"


def fire_section(
    heading: str,
    entries: tuple[peri_scribe.report.gathering.FireReportEntry, ...],
    fact_for: typing.Callable[
        [peri_scribe.report.gathering.FireReportEntry],
        str | None,
    ]
    | None = None,
    *,
    anchors: typing.Mapping[
        peri_scribe.report.gathering.FireReportEntry,
        str,
    ],
) -> list[str]:
    """Return the Markdown lines for one report section.

    Args:
        heading: The section's heading.
        entries: The section's fires, already ordered.
        fact_for: The section-specific leading fact for each fire, or None when the
            section has no leading fact.
        anchors: The details heading's anchor for each fire, keyed by its report entry.

    Returns:
        The section's lines, including the heading and a trailing blank line.
    """
    lines = [f"## {heading}", ""]
    if not entries:
        lines.append("_No fires._")
    elif fact_for is None:
        lines.extend(fire_bullet(entry, anchor=anchors.get(entry)) for entry in entries)
    else:
        lines.extend(
            fire_bullet(
                entry,
                primary_fact=fact_for(entry),
                anchor=anchors.get(entry),
            )
            for entry in entries
        )
    lines.append("")
    return lines


def fire_detail_lines(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> list[str]:
    """Return *entry*'s details mini section, headed by its name.

    The section opens with the fire as a ``###`` heading and lists the fire's area,
    containment, discovery time, and growth over the fast-growth window; a fact that is
    unknown is left out rather than shown as a placeholder, and growth is shown only
    when it is large enough to display a nonzero value, so a fire that merely held
    steady is not described as having grown.

    Args:
        entry: The fire to describe.

    Returns:
        The mini section's lines, including a blank line after the heading.
    """
    lines = [f"### {fire_heading(entry)}", ""]
    facts = [
        fact
        for fact in (
            area_fact(entry),
            containment_fact(entry),
            discovery_fact(entry),
            growth_in_acres_fact(entry)
            if entry.growth_in_acres is not None and entry.growth_in_acres > 0
            else None,
            growth_in_percent_fact(entry)
            if (
                entry.growth_in_percent is not None
                and entry.growth_in_percent >= MINIMUM_DISPLAYED_GROWTH_IN_PERCENT
            )
            else None,
        )
        if fact is not None
    ]
    lines.extend(f"- {fact}" for fact in facts)
    return lines


def fire_details_section(
    entries: tuple[peri_scribe.report.gathering.FireReportEntry, ...],
) -> list[str]:
    """Return the closing fire-details section's Markdown lines.

    Each fire in *entries*, already ordered by name, becomes its own ``###`` mini
    section under the ``## Fire Details`` heading.

    Args:
        entries: The report's detail entries, one per distinct fire, ordered by name.

    Returns:
        The section's lines, including the heading and a trailing blank line.
    """
    lines = ["## Fire Details", ""]
    if not entries:
        lines.append("_No fires._")
    else:
        for entry in entries:
            lines.extend(fire_detail_lines(entry))
            lines.append("")
    lines.append("")
    return lines


def markdown_text(
    report: peri_scribe.report.gathering.FireReport,
    year: int,
) -> str:
    """Return *report* as Markdown text.

    Args:
        report: The gathered report.
        year: The year the report describes.

    Returns:
        The Markdown document text.
    """
    anchors = {
        entry: heading_anchor(fire_heading(entry)) for entry in report.fire_details
    }
    lines = [f"# PeriScribe Fires {year}", ""]
    lines.extend(
        fire_section(
            "New, Notable Fires",
            report.new_notable_fires,
            discovery_fact,
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_section(
            "Fastest Growing Fires (acres)",
            report.fastest_growing_by_acres,
            growth_in_acres_fact,
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_section(
            "Fastest Growing Fires (%)",
            report.fastest_growing_by_percent,
            growth_in_percent_fact,
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_section(
            "Top Fires",
            report.top_fires,
            anchors=anchors,
        ),
    )
    lines.extend(fire_details_section(report.fire_details))
    return "\n".join(lines).rstrip() + "\n"


def render_markdown_report(
    report: peri_scribe.report.gathering.FireReport,
    year_directory: pathlib.Path,
) -> pathlib.Path:
    """Write *report* as Markdown under *year_directory*.

    The report is written to ``{year_directory}/reports/PeriScribe Fires {year}.md``,
    creating the reports directory when it does not exist.

    Args:
        report: The gathered report.
        year_directory: The year directory, whose name is the year.

    Returns:
        The written report path.
    """
    path = markdown_report_path(year_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text(report, int(year_directory.name)), encoding="utf-8")
    return path
