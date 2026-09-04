"""Tests for peri_scribe.report.markdown."""

from __future__ import annotations

import datetime
import pathlib

import peri_scribe.models
import peri_scribe.report.gathering
import peri_scribe.report.markdown


REPORT_SECTION_COUNT = 5


def make_entry(
    name: str,
    *,
    identifier: str | None = None,
    area_in_acres: float | None = None,
    percent_contained: float | None = None,
    score: int | None = None,
    growth_in_acres: float | None = None,
    growth_in_percent: float | None = None,
    discovery_time: datetime.datetime | None = None,
) -> peri_scribe.report.gathering.FireReportEntry:
    """Return a report entry with only the requested facts set.

    Args:
        name: The fire's name.
        identifier: The fire's identifier, or None.
        area_in_acres: The fire's latest area, or None.
        percent_contained: The fire's containment percentage, or None.
        score: The fire's score, or None.
        growth_in_acres: The fire's acreage growth, or None.
        growth_in_percent: The fire's percent growth, or None.
        discovery_time: The fire's discovery time, or None.

    Returns:
        An active fire entry carrying the requested facts.
    """
    return peri_scribe.report.gathering.FireReportEntry(
        name=name,
        identifier=identifier,
        status=peri_scribe.models.FireStatus.ACTIVE,
        area_in_acres=area_in_acres,
        percent_contained=percent_contained,
        discovery_time=discovery_time,
        growth_in_acres=growth_in_acres,
        growth_in_percent=growth_in_percent,
        score=score,
    )


def test_markdown_report_path_names_year() -> None:
    assert peri_scribe.report.markdown.markdown_report_path(
        pathlib.Path("data/2026"),
    ) == pathlib.Path("data/2026/reports/PeriScribe Fires 2026.md")


def test_fire_bullet_includes_identifier_and_area() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
    )
    assert (
        peri_scribe.report.markdown.fire_bullet(entry)
        == "- **Bug** (id-bug) — 100 acres"
    )


def test_fire_bullet_does_not_show_score() -> None:
    entry = make_entry("Bug", score=400)
    assert peri_scribe.report.markdown.fire_bullet(entry) == "- **Bug**"


def test_fire_bullet_links_label_to_details_anchor() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
    )
    assert (
        peri_scribe.report.markdown.fire_bullet(entry, anchor="bug-id-bug")
        == "- [**Bug** (id-bug)](#bug-id-bug) — 100 acres"
    )


def test_fire_bullet_leads_with_primary_fact() -> None:
    entry = make_entry(
        "Bug",
        identifier="id-bug",
        area_in_acres=100.0,
    )
    assert (
        peri_scribe.report.markdown.fire_bullet(
            entry,
            primary_fact="grew 50 acres in 48 hours",
        )
        == "- **Bug** (id-bug) — grew 50 acres in 48 hours, 100 acres"
    )


def test_fire_bullet_omits_missing_identifier_and_facts() -> None:
    entry = make_entry("Bug")
    assert peri_scribe.report.markdown.fire_bullet(entry) == "- **Bug**"


def test_area_fact_formats_area() -> None:
    entry = make_entry("Bug", area_in_acres=100.0)
    assert peri_scribe.report.markdown.area_fact(entry) == "100 acres"


def test_area_fact_returns_none_without_area() -> None:
    assert peri_scribe.report.markdown.area_fact(make_entry("Bug")) is None


def test_containment_fact_formats_containment() -> None:
    entry = make_entry("Bug", percent_contained=50.0)
    assert peri_scribe.report.markdown.containment_fact(entry) == "50% contained"


def test_containment_fact_returns_none_without_containment() -> None:
    assert peri_scribe.report.markdown.containment_fact(make_entry("Bug")) is None


def test_discovery_fact_returns_none_without_discovery_time() -> None:
    assert peri_scribe.report.markdown.discovery_fact(make_entry("Bug")) is None


def test_growth_in_acres_fact_returns_none_without_growth() -> None:
    assert peri_scribe.report.markdown.growth_in_acres_fact(make_entry("Bug")) is None


def test_growth_in_percent_fact_returns_none_without_growth() -> None:
    assert peri_scribe.report.markdown.growth_in_percent_fact(make_entry("Bug")) is None


def test_fire_heading_includes_identifier() -> None:
    entry = make_entry("Bug", identifier="id-bug")
    assert peri_scribe.report.markdown.fire_heading(entry) == "Bug (id-bug)"


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
        "### Bug (id-bug)",
        "",
        "- 100 acres",
        "- 50% contained",
        "- discovered 07/31 17:00 PDT",
        "- +5,000 acres in 48 hours",
        "- +10% in 48 hours",
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
        "### Bug (id-bug)",
        "",
        "- 100 acres",
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
        "### Bug (id-bug)",
        "",
        "- 100 acres",
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
    assert "[**Bug** (id-bug)](#bug-id-bug)" in text
    assert "[**Big** (id-big)](#big-id-big)" in text
    assert "+5,000 acres in 48 hours" in text
    assert "+50% in 48 hours" in text
    assert "### Big (id-big)" in text
    assert "100,000 acres" in text


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
