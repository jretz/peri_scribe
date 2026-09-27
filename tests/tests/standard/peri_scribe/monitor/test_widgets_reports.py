"""Published report links reach their owning details in the terminal monitor."""

import pathlib
import re
import unittest.mock

import pytest
import textual.widgets

import peri_scribe.monitor.widgets
import tests.helpers.factories.peri_scribe.monitor.reports
import tests.helpers.fixtures.peri_scribe.monitor.widgets
import tests.helpers.textual


@pytest.mark.asyncio
async def test_report_viewer_resolves_generated_summary_anchor(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
    tmp_path: pathlib.Path,
) -> None:
    source = tests.helpers.factories.peri_scribe.monitor.reports.generated_report(
        tmp_path,
        ("Moonshine",),
    )
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document
    await document.update(source)
    await report_session.refresh()
    anchor = re.findall(r"\]\(#([^)]*)\)", source)[0]

    assert await tests.helpers.textual.invoke(document.goto_anchor, anchor)


@pytest.mark.parametrize(
    "names",
    [
        ("Moonshine", "Moonshine"),
        ("Bug", "Bug!", "Bug-1"),
        ("Top Fires", "Fire Details", "PeriScribe Fires 2026"),
        ("Café / 東京", "Café -- 東京", "[Fire] & <Fire>"),
    ],
)
@pytest.mark.asyncio
async def test_report_viewer_generated_links_reach_each_owning_detail(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
) -> None:
    source = tests.helpers.factories.peri_scribe.monitor.reports.generated_report(
        tmp_path,
        names,
    )
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document
    await document.update(source)
    await report_session.refresh()
    headings = tuple(document.query("MarkdownH3"))
    scrolls = tuple(
        unittest.mock.Mock(wraps=heading.scroll_visible) for heading in headings
    )
    for heading, scroll in zip(headings, scrolls, strict=True):
        monkeypatch.setattr(heading, "scroll_visible", scroll)
    links = re.findall(r"\]\((#[^)]*)\)", source)
    assert len(links) == len(names)

    for index, href in enumerate(links):
        await tests.helpers.textual.invoke(
            document.post_message,
            textual.widgets.Markdown.LinkClicked(document, href),
        )
        await report_session.refresh()
        assert tuple(scroll.call_count for scroll in scrolls) == tuple(
            int(position <= index) for position in range(len(names))
        )


@pytest.mark.asyncio
async def test_report_viewer_refresh_discards_removed_detail_anchors(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
    tmp_path: pathlib.Path,
) -> None:
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document
    original = tests.helpers.factories.peri_scribe.monitor.reports.generated_report(
        tmp_path,
        ("Moonshine", "Moonshine"),
    )
    await document.update(original)
    await report_session.refresh()
    removed = re.findall(r"\]\(#([^)]*)\)", original)[1]
    assert await tests.helpers.textual.invoke(document.goto_anchor, removed)

    replacement = tests.helpers.factories.peri_scribe.monitor.reports.generated_report(
        tmp_path,
        ("Replacement",),
    )
    await document.update(replacement)
    await report_session.refresh()

    assert not await tests.helpers.textual.invoke(document.goto_anchor, removed)


@pytest.mark.parametrize(
    "source",
    [
        '<a id="fire-detail:0" class="other"></a>\n\n### Moonshine',
        '```html\n<a id="fire-detail:0"></a>\n```\n\n### Moonshine',
        '`<a id="fire-detail:0"></a>`\n\n### Moonshine',
    ],
)
@pytest.mark.asyncio
async def test_report_viewer_ignores_report_anchor_text_outside_canonical_html(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
    source: str,
) -> None:
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document
    await document.update(source)
    await report_session.refresh()

    assert not await tests.helpers.textual.invoke(document.goto_anchor, "fire-detail:0")


@pytest.mark.asyncio
async def test_report_viewer_rejects_anchor_without_following_content(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
) -> None:
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document
    await document.update('### Moonshine\n\n<a id="fire-detail:0"></a>')
    await report_session.refresh()

    assert not await tests.helpers.textual.invoke(document.goto_anchor, "fire-detail:0")


@pytest.mark.asyncio
async def test_report_viewer_preserves_ordinary_heading_navigation(
    report_session: tests.helpers.fixtures.peri_scribe.monitor.widgets.ReportSession,
) -> None:
    document = report_session.app.query_one(
        peri_scribe.monitor.widgets.ReportViewer,
    ).document

    assert await tests.helpers.textual.invoke(document.goto_anchor, "moonshine")
