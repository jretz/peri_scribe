"""Tests for peri_scribe.report.markdown."""

from __future__ import annotations

import datetime
import pathlib

import peri_scribe.kml.descriptions
import peri_scribe.models
import peri_scribe.report.gathering
import peri_scribe.report.markdown


REPORT_SECTION_COUNT = 5
GROWTH_SECTION_COUNT = 2


def make_entry(
    name: str,
    *,
    identifier: str | None = None,
    description: peri_scribe.kml.descriptions.FireDescription | None = None,
    area_in_acres: float | None = None,
    percent_contained: float | None = None,
    discovery_time: datetime.datetime | None = None,
    score: int | None = None,
    growth_in_acres: float | None = None,
    growth_in_percent: float | None = None,
) -> peri_scribe.report.gathering.FireReportEntry:
    """Return a report entry carrying only the requested facts.

    When no *description* is given one is built from the requested facts, mirroring how
    the gathering step pairs an entry with the fire's balloon description, so the
    details rows read from the same source the balloon reads.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.
        description: The fire's balloon description, or None to build one.
        area_in_acres: The fire's latest area, or None.
        percent_contained: The fire's containment percentage, or None.
        discovery_time: The fire's discovery time, or None.
        score: The fire's score, or None.
        growth_in_acres: The fire's acreage growth, or None.
        growth_in_percent: The fire's percent growth, or None.

    Returns:
        An active fire entry carrying the requested facts.
    """
    if description is None:
        description = peri_scribe.kml.descriptions.FireDescription(
            identifier=identifier,
            area_in_acres=area_in_acres,
            percent_contained=percent_contained,
            discovery_time=discovery_time,
        )
    return peri_scribe.report.gathering.FireReportEntry(
        name=name,
        identifier=identifier,
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=description,
        growth_in_acres=growth_in_acres,
        growth_in_percent=growth_in_percent,
        score=score,
    )


def test_markdown_report_path_names_year() -> None:
    assert peri_scribe.report.markdown.markdown_report_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/reports/PeriScribe Fires 2026.md")


def test_discovery_cell_formats_discovery_time() -> None:
    entry = make_entry(
        "Bug",
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )
    assert peri_scribe.report.markdown.discovery_cell(entry) == "07/31 17:00 PDT"


def test_discovery_cell_returns_none_without_discovery_time() -> None:
    assert peri_scribe.report.markdown.discovery_cell(make_entry("Bug")) is None


def test_growth_in_acres_cell_returns_signed_growth() -> None:
    entry = make_entry("Bug", growth_in_acres=3394.0)
    assert peri_scribe.report.markdown.growth_in_acres_cell(entry) == "+3,394 acres"


def test_growth_in_acres_cell_returns_none_without_growth() -> None:
    assert peri_scribe.report.markdown.growth_in_acres_cell(make_entry("Bug")) is None


def test_growth_in_percent_cell_returns_signed_growth() -> None:
    entry = make_entry("Bug", growth_in_percent=50.0)
    assert peri_scribe.report.markdown.growth_in_percent_cell(entry) == "+50%"


def test_growth_in_percent_cell_returns_none_without_growth() -> None:
    assert peri_scribe.report.markdown.growth_in_percent_cell(make_entry("Bug")) is None


def test_area_fact_formats_area() -> None:
    entry = make_entry("Bug", area_in_acres=100.0)
    assert peri_scribe.report.markdown.area_fact(entry) == "100 acres"


def test_area_fact_returns_none_without_area() -> None:
    assert peri_scribe.report.markdown.area_fact(make_entry("Bug")) is None


def test_area_fact_returns_none_without_description() -> None:
    entry = peri_scribe.report.gathering.FireReportEntry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=None,
    )
    assert peri_scribe.report.markdown.area_fact(entry) is None


def test_discovery_cell_returns_none_without_description() -> None:
    entry = peri_scribe.report.gathering.FireReportEntry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=None,
    )
    assert peri_scribe.report.markdown.discovery_cell(entry) is None


def test_fire_heading_shows_name_only() -> None:
    entry = make_entry("Bug", identifier="id-bug")
    assert peri_scribe.report.markdown.fire_heading(entry) == "Bug"


def test_fire_heading_without_identifier() -> None:
    assert peri_scribe.report.markdown.fire_heading(make_entry("Bug")) == "Bug"


def test_heading_anchor_matches_github_style() -> None:
    assert (
        peri_scribe.report.markdown.heading_anchor("Bug (2026-idipf-000347)")
        == "bug-2026-idipf-000347"
    )
    assert (
        peri_scribe.report.markdown.heading_anchor("E. Evans Creek Rd 18000")
        == "e-evans-creek-rd-18000"
    )


def test_markdown_table_lines_renders_headings_and_rows() -> None:
    lines = peri_scribe.report.markdown.markdown_table_lines(
        ("Fire", "Area"),
        (("**Bug**", "100 acres"),),
    )

    assert lines == [
        "| Fire    | Area      |",
        "| ------- | --------- |",
        "| **Bug** | 100 acres |",
    ]


def test_markdown_table_lines_aligns_bars() -> None:
    lines = peri_scribe.report.markdown.markdown_table_lines(
        ("Fire", "Area"),
        (("**Bug**", "100 acres"), ("Fire", "50 acres")),
    )
    pipe_positions = [
        tuple(index for index, character in enumerate(line) if character == "|")
        for line in lines
    ]

    assert all(positions == pipe_positions[0] for positions in pipe_positions)


def test_markdown_table_lines_right_aligns_marked_columns() -> None:
    lines = peri_scribe.report.markdown.markdown_table_lines(
        ("Fire", "Area"),
        (("**Bug**", "100 acres"), ("Fire", "50 acres")),
        right_aligned_columns=(False, True),
    )

    assert lines == [
        "| Fire    |      Area |",
        "| ------- | --------: |",
        "| **Bug** | 100 acres |",
        "| Fire    |  50 acres |",
    ]


def test_fire_table_section_renders_linked_rows_with_blank_missing_cells() -> None:
    bug = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
    )
    fire = make_entry(
        "Fire",
        identifier="id-fire",
        growth_in_acres=5000.0,
    )
    lines = peri_scribe.report.markdown.fire_table_section(
        "Fastest Growing Fires (acres)",
        (bug, fire),
        columns=(
            (
                peri_scribe.report.markdown.GROWTH_LABEL,
                peri_scribe.report.markdown.growth_in_acres_cell,
                True,
            ),
            (
                peri_scribe.report.markdown.AREA_LABEL,
                peri_scribe.report.markdown.area_fact,
                True,
            ),
        ),
        anchors={bug: "bug-id-bug", fire: "fire-id-fire"},
    )

    assert lines == [
        "## Fastest Growing Fires (acres)",
        "",
        "| Fire                      | 48-Hour Growth |      Area |",
        "| ------------------------- | -------------: | --------: |",
        "| [**Bug**](#bug-id-bug)    |                | 100 acres |",
        "| [**Fire**](#fire-id-fire) |   +5,000 acres |           |",
        "",
    ]


def test_fire_table_section_renders_name_without_anchor() -> None:
    entry = make_entry("Bug", area_in_acres=100.0)
    lines = peri_scribe.report.markdown.fire_table_section(
        "Top Fires",
        (entry,),
        columns=(
            (
                peri_scribe.report.markdown.AREA_LABEL,
                peri_scribe.report.markdown.area_fact,
                True,
            ),
        ),
        anchors={},
    )

    assert "| **Bug** | 100 acres |" in lines


def test_fire_table_section_marks_empty_section() -> None:
    lines = peri_scribe.report.markdown.fire_table_section(
        "Top Fires",
        (),
        columns=(
            (
                peri_scribe.report.markdown.AREA_LABEL,
                peri_scribe.report.markdown.area_fact,
                True,
            ),
        ),
        anchors={},
    )

    assert lines == ["## Top Fires", "", "_No fires._", ""]


def test_fire_detail_rows_show_the_balloon_facts() -> None:
    description = peri_scribe.kml.descriptions.FireDescription(
        identifier="2026-idipf-000347",
        source="WFIGS",
        mission="B-1",
        area_in_acres=4797.0,
        exterior_perimeter_in_miles=27.3,
        percent_contained=42.0,
        estimated_cost_to_date_in_dollars=32168278.0,
        total_personnel=147.0,
        protecting_unit="IDIPF",
        discovery_time=datetime.datetime(2026, 7, 8, 15, 29, tzinfo=datetime.UTC),
        observation_time=datetime.datetime(2026, 9, 2, 20, 36, tzinfo=datetime.UTC),
        incident_type="WF",
        incident_complexity="Type 3 Incident; Type 3 Team",
        fuel_model="Timber (Litter and Understory)",
        fire_behavior="Minimal; Backing",
        landowner_category="USFS",
        of_note="Over 1,000 acres.",
    )
    entry = make_entry("Bug", identifier="2026-idipf-000347", description=description)

    assert peri_scribe.report.markdown.fire_detail_rows(entry) == (
        ("Area", "4,797 acres"),
        ("Exterior perimeter", "27.3 miles"),
        ("Containment", "42% (11.5 of 27.3 miles)"),
        ("Cost to date", "$32,168,278"),
        ("Personnel", "147"),
        ("Source", "WFIGS"),
        ("Identifier", "2026-idipf-000347"),
        ("Mission", "B-1"),
        ("Protecting unit", "IDIPF"),
        ("Discovery", "07/08 08:29 PDT"),
        ("Last update", "09/02 13:36 PDT"),
        ("Incident type", "WF"),
        ("Incident complexity", "Type 3 Incident; Type 3 Team"),
        ("Fuel model", "Timber (Litter and Understory)"),
        ("Fire behavior", "Minimal; Backing"),
        ("Landowner category", "USFS"),
        ("Of note", "Over 1,000 acres."),
    )


def test_fire_detail_rows_append_growth_after_balloon_facts() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
        growth_in_acres=5000.0,
        growth_in_percent=10.0,
    )
    assert peri_scribe.report.markdown.fire_detail_rows(entry) == (
        ("Area", "100 acres"),
        ("Identifier", "id-bug"),
        ("48-Hour Growth (acres)", "+5,000 acres"),
        ("48-Hour Growth (%)", "+10%"),
    )


def test_fire_detail_rows_show_growth_without_description() -> None:
    entry = peri_scribe.report.gathering.FireReportEntry(
        name="Bug",
        identifier="id-bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
        description=None,
        growth_in_acres=5000.0,
    )
    assert peri_scribe.report.markdown.fire_detail_rows(entry) == (
        ("48-Hour Growth (acres)", "+5,000 acres"),
    )


def test_fire_detail_lines_render_mini_section() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
        percent_contained=50.0,
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        growth_in_acres=5000.0,
        growth_in_percent=10.0,
    )
    assert peri_scribe.report.markdown.fire_detail_lines(entry) == [
        "### Bug",
        "",
        "| Fact                   | Value           |",
        "| ---------------------- | --------------- |",
        "| Area                   | 100 acres       |",
        "| Containment            | 50%             |",
        "| Identifier             | id-bug          |",
        "| Discovery              | 07/31 17:00 PDT |",
        "| 48-Hour Growth (acres) | +5,000 acres    |",
        "| 48-Hour Growth (%)     | +10%            |",
    ]


def test_fire_detail_lines_heading_without_facts() -> None:
    assert peri_scribe.report.markdown.fire_detail_lines(
        make_entry("Bug"),
    ) == ["### Bug", ""]


def test_fire_detail_lines_omit_zero_growth() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
        growth_in_acres=0.0,
        growth_in_percent=0.0,
    )
    assert peri_scribe.report.markdown.fire_detail_lines(entry) == [
        "### Bug",
        "",
        "| Fact       | Value     |",
        "| ---------- | --------- |",
        "| Area       | 100 acres |",
        "| Identifier | id-bug    |",
    ]


def test_fire_detail_lines_omit_shrinkage_and_tiny_percent_growth() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
        growth_in_acres=-5.0,
        growth_in_percent=0.05,
    )
    assert peri_scribe.report.markdown.fire_detail_lines(entry) == [
        "### Bug",
        "",
        "| Fact       | Value     |",
        "| ---------- | --------- |",
        "| Area       | 100 acres |",
        "| Identifier | id-bug    |",
    ]


def test_markdown_text_renders_title_sections_and_details() -> None:
    bug = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )
    fire = make_entry(
        "Fire",
        identifier="id-fire",
        growth_in_acres=5000.0,
    )
    percent = make_entry(
        "Percent",
        identifier="id-percent",
        growth_in_percent=50.0,
    )
    big = make_entry(
        "Big",
        identifier="id-big",
        area_in_acres=100000.0,
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(bug,),
        fastest_growing_by_acres=(fire,),
        fastest_growing_by_percent=(percent,),
        top_fires=(big,),
        fire_details=(big, bug, fire, percent),
    )
    text = peri_scribe.report.markdown.markdown_text(report, 2026)

    assert "# PeriScribe Fires 2026" in text
    assert "## New, Notable Fires" in text
    assert "## Fastest Growing Fires (acres)" in text
    assert "## Fastest Growing Fires (%)" in text
    assert "## Top Fires" in text
    assert "## Fire Details" in text
    assert text.index("## Fire Details") > text.index("## Top Fires")
    summary_lines = text.split("## Fire Details")[0].splitlines()
    assert (
        sum(
            1
            for line in summary_lines
            if line.startswith("| Fire") and "48-Hour Growth" in line
        )
        == GROWTH_SECTION_COUNT
    )
    assert any(
        line.startswith("| Fire") and "Discovery" in line for line in summary_lines
    )
    assert "[**Bug**](#bug)" in text
    assert "[**Fire**](#fire)" in text
    assert "[**Percent**](#percent)" in text
    assert "[**Big**](#big)" in text
    assert "### Big" in text
    assert "| Identifier" in text
    assert "id-big" in text
    assert "id-bug" in text
    assert "id-fire" in text
    assert "id-percent" in text
    assert "07/31 17:00 PDT" in text
    assert "100,000 acres" in text
    assert "+5,000 acres" in text
    assert "+50%" in text


def test_markdown_text_marks_empty_section() -> None:
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )
    text = peri_scribe.report.markdown.markdown_text(report, 2026)

    assert text.count("_No fires._") == REPORT_SECTION_COUNT


def test_render_markdown_report_writes_file(tmp_path: pathlib.Path) -> None:
    year_directory = tmp_path / "2026"
    year_directory.mkdir()
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )

    path = peri_scribe.report.markdown.render_markdown_report(
        report,
        year_directory,
    )

    assert path == year_directory / "reports" / "PeriScribe Fires 2026.md"
    assert "PeriScribe Fires 2026" in path.read_text(encoding="utf-8")
