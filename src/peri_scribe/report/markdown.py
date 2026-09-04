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

# The growth facts' labels, spelled once so the summary tables' column headings and the
# details tables' row labels stay in step; they reuse the fast-growth window so the
# hours they name cannot drift from the window the growth is measured over.
GROWTH_LABEL = f"{FAST_GROWTH_WINDOW_IN_HOURS}-Hour Growth"
GROWTH_IN_ACRES_LABEL = f"{GROWTH_LABEL} (acres)"
GROWTH_IN_PERCENT_LABEL = f"{GROWTH_LABEL} (%)"

# The labels the summary tables' headings borrow from the fire's balloon facts, kept as
# aliases here so a heading and the same fact's details row cannot drift apart.
AREA_LABEL = peri_scribe.kml.descriptions.AREA_LABEL
DISCOVERY_LABEL = peri_scribe.kml.descriptions.DISCOVERY_LABEL

# A callable that returns one fire's text for one table column, or None when the fire
# lacks that fact.
ColumnTextFor = typing.Callable[
    [peri_scribe.report.gathering.FireReportEntry],
    str | None,
]


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


def discovery_cell(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s discovery time for a table cell, or None when unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The discovery time, or None.
    """
    if entry.description is None:
        return None
    return peri_scribe.kml.descriptions.format_pacific_time(
        entry.description.discovery_time,
    )


def growth_in_acres_cell(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s signed acreage growth for a table cell, or None when unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The signed growth in acres, or None.
    """
    if entry.growth_in_acres is None:
        return None
    return f"+{peri_scribe.kml.descriptions.format_in_acres(entry.growth_in_acres)}"


def growth_in_percent_cell(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s signed percent growth for a table cell, or None when unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The signed growth in percent, or None.
    """
    if entry.growth_in_percent is None:
        return None
    return f"+{peri_scribe.kml.descriptions.format_in_percent(entry.growth_in_percent)}"


def area_fact(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str | None:
    """Return *entry*'s area fact, or None when its area is unknown.

    Args:
        entry: The fire to describe.

    Returns:
        The area phrase, or None.
    """
    if entry.description is None:
        return None
    return peri_scribe.kml.descriptions.format_in_acres(
        entry.description.area_in_acres,
    )


def fire_heading(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> str:
    """Return *entry*'s details heading text.

    The heading carries the fire's name alone; the identifier is shown as the
    ``Identifier`` row of the fire's details table, keeping the heading short and the
    anchor it names simple.

    Args:
        entry: The fire to describe.

    Returns:
        The heading text, without its Markdown ``###`` prefix.
    """
    return entry.name


def heading_anchor(heading: str) -> str:
    """Return the anchor a Markdown renderer assigns to *heading*.

    GitHub-style anchors keep letters, digits, hyphens, and underscores, replace runs of
    spaces with hyphens, and lowercase the result, so a summary table's fire name can
    link to the fire's details heading.

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


def markdown_table_lines(
    column_headings: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    right_aligned_columns: tuple[bool, ...] = (),
) -> list[str]:
    """Return *column_headings* and *rows* as a Markdown table's lines.

    Each cell is padded with spaces to the width of the widest cell in its column, so
    the table's bars line up when the text is read in a monospace font. A column that
    *right_aligned_columns* marks right-aligns its heading and data and fills its dash
    cell with dashes that end in a colon, so both the plain text and rendered Markdown
    line the column up at the right edge. The table opens with a heading row, then a row
    of dashes that span each column and that Markdown renderers read as the boundary
    before the data rows, each holding one cell text per heading.

    Args:
        column_headings: The table's column headings.
        rows: The table's rows, each with one cell text per column.
        right_aligned_columns: One flag per column, or none when every column stays
            left aligned.

    Returns:
        The table's lines, without a trailing blank line.
    """
    column_widths = tuple(
        max(len(cell) for cell in column)
        for column in zip(column_headings, *rows, strict=True)
    )
    if not right_aligned_columns:
        right_aligned_columns = (False,) * len(column_headings)
    dash_cells = [
        "-" * (width - 1) + ":" if right_aligned else "-" * width
        for width, right_aligned in zip(
            column_widths,
            right_aligned_columns,
            strict=True,
        )
    ]
    lines = [
        "| "
        + " | ".join(
            heading.rjust(width) if right_aligned else heading.ljust(width)
            for heading, width, right_aligned in zip(
                column_headings,
                column_widths,
                right_aligned_columns,
                strict=True,
            )
        )
        + " |",
        "| " + " | ".join(dash_cells) + " |",
    ]
    for row in rows:
        cells = " | ".join(
            cell.rjust(width) if right_aligned else cell.ljust(width)
            for cell, width, right_aligned in zip(
                row,
                column_widths,
                right_aligned_columns,
                strict=True,
            )
        )
        lines.append(f"| {cells} |")
    return lines


def fire_table_section(
    heading: str,
    entries: tuple[peri_scribe.report.gathering.FireReportEntry, ...],
    *,
    columns: tuple[tuple[str, ColumnTextFor, bool], ...],
    anchors: typing.Mapping[
        peri_scribe.report.gathering.FireReportEntry,
        str,
    ],
) -> list[str]:
    """Return the Markdown lines for one report section, rendered as a table.

    The section's fires become the table's rows, each opening with the fire's name,
    linked to its details heading through *anchors*; the *columns* that follow hold the
    facts the section leads with. A fact that is unknown shows as an empty cell rather
    than a placeholder, so the row stays aligned, and a column whose final flag is set
    right-aligns its heading and numeric values and marks the table's dash row with an
    alignment colon. A section without fires shows ``_No fires._`` in place of a table.

    Args:
        heading: The section's heading.
        entries: The section's fires, already ordered.
        columns: The columns that follow the fire-name column, each holding its heading,
            the cell text for one fire, and whether the column's numbers align to the
            right.
        anchors: The details heading's anchor for each fire, keyed by its report entry.

    Returns:
        The section's lines, including the heading and a trailing blank line.
    """
    lines = [f"## {heading}", ""]
    if not entries:
        lines.append("_No fires._")
    else:
        column_headings: list[str] = ["Fire"]
        cell_text_fors: list[ColumnTextFor] = []
        right_aligned_columns: list[bool] = [False]
        for column_heading, cell_text_for, right_aligned in columns:
            column_headings.append(column_heading)
            cell_text_fors.append(cell_text_for)
            right_aligned_columns.append(right_aligned)
        rows: list[tuple[str, ...]] = []
        for entry in entries:
            label = f"**{entry.name}**"
            anchor = anchors.get(entry)
            if anchor is not None:
                label = f"[{label}](#{anchor})"
            cells = [label]
            for cell_text_for in cell_text_fors:
                cell_text = cell_text_for(entry)
                cells.append("" if cell_text is None else cell_text)
            rows.append(tuple(cells))
        lines.extend(
            markdown_table_lines(
                tuple(column_headings),
                tuple(rows),
                right_aligned_columns=tuple(right_aligned_columns),
            ),
        )
    lines.append("")
    return lines


def fire_detail_rows(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> tuple[tuple[str, str], ...]:
    """Return the label/value rows *entry*'s details table shows.

    The rows are the facts the fire's KMZ balloon table shows, with the same labels and
    text and in the balloon's order, so the report and the map carry the same data for
    each fire; a fact the fire lacks is left out rather than shown as a placeholder.
    Growth over the fast-growth window follows when it is large enough to display a
    nonzero value, so a fire that merely held steady is not described as having grown.

    Args:
        entry: The fire to describe.

    Returns:
        The details table's rows, each holding a label and a value.
    """
    rows: list[tuple[str, str]] = []
    if entry.description is not None:
        for label, value in peri_scribe.kml.descriptions.description_rows(
            entry.description,
        ):
            if value is not None:
                rows.append((label, value))
    if entry.growth_in_acres is not None and entry.growth_in_acres > 0:
        growth_in_acres = growth_in_acres_cell(entry)
        if growth_in_acres is not None:
            rows.append((GROWTH_IN_ACRES_LABEL, growth_in_acres))
    if (
        entry.growth_in_percent is not None
        and entry.growth_in_percent >= MINIMUM_DISPLAYED_GROWTH_IN_PERCENT
    ):
        growth_in_percent = growth_in_percent_cell(entry)
        if growth_in_percent is not None:
            rows.append((GROWTH_IN_PERCENT_LABEL, growth_in_percent))
    return tuple(rows)


def fire_detail_lines(
    entry: peri_scribe.report.gathering.FireReportEntry,
) -> list[str]:
    """Return *entry*'s details mini section, headed by its name.

    The section opens with the fire's name as a ``###`` heading and then shows each
    known fact from the fire's details rows as one row of a small label/value table, so
    the table carries every fact the fire's KMZ balloon shows.

    Args:
        entry: The fire to describe.

    Returns:
        The mini section's lines, including a blank line after the heading.
    """
    lines = [f"### {fire_heading(entry)}", ""]
    rows = fire_detail_rows(entry)
    if rows:
        lines.extend(markdown_table_lines(("Fact", "Value"), rows))
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
        fire_table_section(
            "New, Notable Fires",
            report.new_notable_fires,
            columns=(
                (DISCOVERY_LABEL, discovery_cell, False),
                (AREA_LABEL, area_fact, True),
            ),
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_table_section(
            "Fastest Growing Fires (acres)",
            report.fastest_growing_by_acres,
            columns=(
                (GROWTH_LABEL, growth_in_acres_cell, True),
                (AREA_LABEL, area_fact, True),
            ),
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_table_section(
            "Fastest Growing Fires (%)",
            report.fastest_growing_by_percent,
            columns=(
                (GROWTH_LABEL, growth_in_percent_cell, True),
                (AREA_LABEL, area_fact, True),
            ),
            anchors=anchors,
        ),
    )
    lines.extend(
        fire_table_section(
            "Top Fires",
            report.top_fires,
            columns=((AREA_LABEL, area_fact, True),),
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
