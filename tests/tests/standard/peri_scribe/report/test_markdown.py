"""Tests for peri_scribe.report.markdown."""

from __future__ import annotations

import datetime
import pathlib

import peri_scribe.kml.descriptions
import peri_scribe.models
import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.helpers.factories.peri_scribe.report.markdown
from peri_scribe.units import units


# The summary sections whose location column headings appear when the report holds a
# located fire in each of them: New, Notable Fires and Top Fires.


def test_discovery_cell_formats_discovery_time() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )
    assert peri_scribe.report.markdown.discovery_cell(entry) == "07/31 17:00 PDT"


def test_discovery_cell_returns_none_without_discovery_time() -> None:
    assert (
        peri_scribe.report.markdown.discovery_cell(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        is None
    )


def test_growth_cell_returns_signed_growth() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        growth=3394.0,
    )
    assert peri_scribe.report.markdown.growth_cell(entry) == "+3,394 acres"


def test_growth_cell_returns_none_without_growth() -> None:
    assert (
        peri_scribe.report.markdown.growth_cell(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        is None
    )


def test_growth_percent_cell_returns_signed_growth() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        growth_percent=50.0,
    )
    assert peri_scribe.report.markdown.growth_percent_cell(entry) == "+50%"


def test_growth_percent_cell_returns_none_without_growth() -> None:
    assert (
        peri_scribe.report.markdown.growth_percent_cell(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        is None
    )


def test_area_fact_formats_area() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        area=100.0,
    )
    assert peri_scribe.report.markdown.area_fact(entry) == "100 acres"


def test_area_fact_returns_none_without_area() -> None:
    assert (
        peri_scribe.report.markdown.area_fact(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        is None
    )


def test_area_fact_returns_none_without_description() -> None:
    entry = peri_scribe.report.gathering.FireReportEntry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    assert peri_scribe.report.markdown.area_fact(entry) is None


def test_discovery_cell_returns_none_without_description() -> None:
    entry = peri_scribe.report.gathering.FireReportEntry(
        name="Bug",
        status=peri_scribe.models.FireStatus.ACTIVE,
    )
    assert peri_scribe.report.markdown.discovery_cell(entry) is None


def test_fire_heading_shows_name_only() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
    )
    assert peri_scribe.report.markdown.fire_heading(entry) == "Bug"


def test_fire_heading_without_identifier() -> None:
    assert (
        peri_scribe.report.markdown.fire_heading(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        == "Bug"
    )


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
    bug = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
    )
    fire = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Fire",
        identifier="id-fire",
        growth=5_000.0,
    )
    lines = peri_scribe.report.markdown.fire_table_section(
        "Fastest Growing Fires (acres)",
        (bug, fire),
        columns=(
            (
                peri_scribe.report.markdown.GROWTH_LABEL,
                peri_scribe.report.markdown.growth_cell,
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
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        area=100.0,
    )
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
        area=4797.0 * units.acres,
        exterior_perimeter=27.3 * units.miles,
        percent_contained=42.0,
        estimated_cost_to_date=32168278.0 * units.dollars,
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
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="2026-idipf-000347",
        description=description,
    )

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
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        growth=5_000.0,
        growth_percent=10.0,
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
        growth=5000.0 * units.acres,
    )
    assert peri_scribe.report.markdown.fire_detail_rows(entry) == (
        ("48-Hour Growth (acres)", "+5,000 acres"),
    )


def test_fire_detail_lines_render_mini_section() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        percent_contained=50.0,
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        growth=5_000.0,
        growth_percent=10.0,
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
        tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
    ) == ["### Bug", ""]


def test_fire_detail_lines_omit_zero_growth() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        growth=0.0,
        growth_percent=0.0,
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
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        growth=-5.0,
        growth_percent=0.05,
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
    bug = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
    )
    fire = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Fire",
        identifier="id-fire",
        growth=5_000.0,
    )
    percent = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Percent",
        identifier="id-percent",
        growth_percent=50.0,
    )
    big = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Big",
        identifier="id-big",
        area=100_000.0,
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(bug,),
        type_one_fires=(),
        fastest_growing_by_acres=(fire,),
        fastest_growing_by_percent=(percent,),
        top_fires=(big,),
        fire_details=(big, bug, fire, percent),
    )
    text = peri_scribe.report.markdown.markdown_text(report, 2026)

    assert "# PeriScribe Fires 2026" in text
    assert "## New, Notable Fires" in text
    assert "## Type 1 Fires" in text
    assert "## Fastest Growing Fires (acres)" in text
    assert "## Fastest Growing Fires (%)" in text
    assert "## Top Fires" in text
    assert "## Fire Details" in text
    assert text.index("## Fire Details") > text.index("## Top Fires")
    assert text.index("## Type 1 Fires") > text.index("## New, Notable Fires")
    assert text.index("## Fastest Growing Fires (acres)") > text.index(
        "## Type 1 Fires",
    )
    summary_lines = text.split("## Fire Details")[0].splitlines()
    assert (
        sum(
            1
            for line in summary_lines
            if line.startswith("| Fire") and "48-Hour Growth" in line
        )
        == tests.helpers.factories.peri_scribe.report.markdown.GROWTH_SECTION_COUNT
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
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )
    text = peri_scribe.report.markdown.markdown_text(report, 2026)

    assert (
        text.count("_No fires._")
        == tests.helpers.factories.peri_scribe.report.markdown.REPORT_SECTION_COUNT
    )


def test_markdown_text_renders_type_one_section_between_new_and_fastest() -> None:
    bug = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        location="15 mi ESE of Portland, OR",
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(bug,),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(bug,),
    )

    text = peri_scribe.report.markdown.markdown_text(report, 2026)
    summary_lines = text.split("## Fire Details")[0].splitlines()
    type_one_heading = summary_lines.index("## Type 1 Fires")

    assert "## New, Notable Fires" in summary_lines[:type_one_heading]
    assert any(
        line.startswith("| Fire") and "Location" in line
        for line in summary_lines[type_one_heading:]
    )
    assert any("[**Bug**](#bug)" in line for line in summary_lines[type_one_heading:])
    assert any(
        "15 mi ESE of Portland, OR" in line for line in summary_lines[type_one_heading:]
    )
    assert any("100 acres" in line for line in summary_lines[type_one_heading:])
    assert "### Bug" in text
    assert text.index("## Fastest Growing Fires (acres)") > text.index(
        "## Type 1 Fires",
    )


def test_render_markdown_report_writes_file(tmp_path: pathlib.Path) -> None:
    year_directory = tmp_path / "2026"
    year_directory.mkdir()
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(),
        fire_details=(),
    )

    path = peri_scribe.report.markdown.render_markdown_report(report, year_directory)

    assert path == year_directory / "reports" / "PeriScribe Fires 2026.md"
    assert "PeriScribe Fires 2026" in path.read_text(encoding="utf-8")


def test_location_cell_returns_location_text() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        location="15 mi ESE of Portland, OR",
    )

    assert (
        peri_scribe.report.markdown.location_cell(entry) == "15 mi ESE of Portland, OR"
    )


def test_location_cell_returns_none_without_location() -> None:
    assert (
        peri_scribe.report.markdown.location_cell(
            tests.helpers.factories.peri_scribe.report.markdown.make_entry("Bug"),
        )
        is None
    )


def test_fire_detail_rows_lead_with_location() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        location="15 mi ESE of Portland, OR",
    )

    assert peri_scribe.report.markdown.fire_detail_rows(entry) == (
        ("Location", "15 mi ESE of Portland, OR"),
        ("Area", "100 acres"),
        ("Identifier", "id-bug"),
    )


def test_fire_detail_lines_show_location_row() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        location="15 mi ESE of Portland, OR",
    )

    assert peri_scribe.report.markdown.fire_detail_lines(entry) == [
        "### Bug",
        "",
        "| Fact       | Value                     |",
        "| ---------- | ------------------------- |",
        "| Location   | 15 mi ESE of Portland, OR |",
        "| Area       | 100 acres                 |",
        "| Identifier | id-bug                    |",
    ]


def test_fire_table_section_renders_location_column() -> None:
    bug = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        location="15 mi ESE of Portland, OR",
    )
    fire = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Fire",
        identifier="id-fire",
        growth=5_000.0,
    )
    lines = peri_scribe.report.markdown.fire_table_section(
        "Fastest Growing Fires (acres)",
        (bug, fire),
        columns=(
            (
                peri_scribe.report.markdown.LOCATION_LABEL,
                peri_scribe.report.markdown.location_cell,
                False,
            ),
            (
                peri_scribe.report.markdown.GROWTH_LABEL,
                peri_scribe.report.markdown.growth_cell,
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

    heading = next(line for line in lines if line.startswith("| Fire"))
    assert "Location" in heading
    bug_row = next(line for line in lines if "[**Bug**](#bug-id-bug)" in line)
    assert "15 mi ESE of Portland, OR" in bug_row
    fire_row = next(line for line in lines if "[**Fire**](#fire-id-fire)" in line)
    assert "15 mi ESE of Portland, OR" not in fire_row
    assert "+5,000 acres" in fire_row


# The summary sections that show the location column when the report holds a located
# fire in each of them: New, Notable Fires and Top Fires.


def test_markdown_text_shows_location_in_sections_and_details() -> None:
    bug = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Bug",
        identifier="id-bug",
        area=100.0,
        discovery_time=datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC),
        location="15 mi ESE of Portland, OR",
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(bug,),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=(bug,),
        fire_details=(bug,),
    )

    text = peri_scribe.report.markdown.markdown_text(report, 2026)

    assert "| Location" in text
    assert "15 mi ESE of Portland, OR" in text
    summary_lines = text.split("## Fire Details")[0].splitlines()
    assert (
        sum(
            1
            for line in summary_lines
            if line.startswith("| Fire") and "Location" in line
        )
        == (
            tests.helpers.factories.peri_scribe.report.markdown
        ).LOCATION_COLUMN_SECTION_COUNT
    )


def test_fire_detail_lines_includes_area_basis() -> None:
    entry = tests.helpers.factories.peri_scribe.report.markdown.make_entry(
        "Example",
        description=peri_scribe.kml.descriptions.FireDescription(
            area=200 * units.acres,
            area_basis="Reported; 09/02 17:00 PDT",
        ),
    )
    assert (
        "| Area basis | Reported; 09/02 17:00 PDT |"
        in peri_scribe.report.markdown.fire_detail_lines(entry)
    )
