"""Distinct fire details retain distinct links after heading normalization."""

import peri_scribe.report.gathering
import peri_scribe.report.markdown
import tests.helpers.factories.peri_scribe.report.markdown


def test_markdown_text_disambiguates_detail_anchors_and_section_collisions() -> None:
    entries = tuple(
        tests.helpers.factories.peri_scribe.report.markdown.make_entry(
            name,
            identifier=str(index),
        )
        for index, name in enumerate(("Bug", "Bug!", "Bug-1", "Top Fires"))
    )
    report = peri_scribe.report.gathering.FireReport(
        new_notable_fires=(),
        type_one_fires=(),
        fastest_growing_by_acres=(),
        fastest_growing_by_percent=(),
        top_fires=entries,
        fire_details=entries,
    )
    text = peri_scribe.report.markdown.markdown_text(report, 2026)
    assert "[**Bug**](#fire-detail:0)" in text
    assert "[**Bug!**](#fire-detail:1)" in text
    assert "[**Bug-1**](#fire-detail:2)" in text
    assert "[**Top Fires**](#fire-detail:3)" in text

    assert all(
        f'<a id="fire-detail:{index}"></a>' in text for index in range(len(entries))
    )
