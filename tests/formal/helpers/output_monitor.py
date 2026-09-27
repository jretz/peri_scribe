"""Connect generated report ownership to the terminal's actual navigation targets."""

from __future__ import annotations

import asyncio
import pathlib
import typing
import unittest.mock

import lxml.html
import markdown_it

import peri_scribe.monitor.widgets
import peri_scribe.report.markdown
import tests.formal.helpers.oracle
import tests.formal.helpers.output_references
import tests.helpers.doubles.peri_scribe.monitor.widgets
import tests.helpers.textual


if typing.TYPE_CHECKING:
    import pytest
    import textual.widgets


def report_references(path: pathlib.Path, count: int) -> list[tuple[str, int]]:
    """Keep the terminal's expected targets tied to the proved ownership contract.

    Args:
        path: Complete saved report containing the summary references.
        count: Number of independently supplied source owners.

    Returns:
        Actual saved reference targets and their formally checked expected owners.
    """
    text = path.read_text(encoding="utf-8")
    rendered = markdown_it.MarkdownIt().enable("table").render(text)
    document = lxml.html.fromstring(rendered)
    links = document.xpath("//a[starts-with(@href, '#')]/@href")
    pairs = tests.formal.helpers.oracle.evaluate(
        [f"rings 0 | {count}"],
        executable="oracleOutputs",
    )[0]
    owners = pairs[1::2]
    expected = [f"fire-detail:{owner}" for owner in owners]
    references = list(
        zip(
            [link[1:] for link in links],
            owners[::2] + owners[1::2] + owners,
            strict=True,
        ),
    )
    resources = list(zip(expected, owners, strict=True))
    assert tests.formal.helpers.output_references.closure(resources, references)
    return references


def check_navigation(
    document: textual.widgets.Markdown,
    references: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observe navigation destinations and their actual rendered identity cells.

    Args:
        document: The mounted document loaded by the real report viewer.
        references: Summary targets paired with their formally checked owners.
        monkeypatch: Record scroll calls while retaining their original behavior.
    """
    headings = list(document.query("MarkdownH3"))
    tables = list(document.query("MarkdownTable"))
    children = list(document.children)
    assert len(headings) == len({owner for _, owner in references})
    destinations = []
    for heading in headings:
        destination = unittest.mock.Mock(wraps=heading.scroll_visible)
        monkeypatch.setattr(heading, "scroll_visible", destination)
        destinations.append(destination)
    for target, owner in references:
        for destination in destinations:
            destination.reset_mock()
        assert document.goto_anchor(target)
        selected = [
            heading
            for heading, destination in zip(headings, destinations, strict=True)
            if destination.called
        ]
        assert len(selected) == 1
        following = children[children.index(selected[0]) + 1 :]
        detail = next(child for child in following if child in tables)
        values = [cell.tooltip for cell in detail.query(".cell")]
        assert f"owner-{owner}" in values
        assert all(
            f"owner-{other}" not in values
            for other in range(len(headings))
            if other != owner
        )


async def check_report(
    directory: pathlib.Path,
    names: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve saved report references to mounted, source-owned detail tables.

    Args:
        directory: Isolated report output location.
        names: Distinct owners' names, including heading collisions and markup.
        monkeypatch: Record actual scroll destinations without replacing navigation.
    """
    prepared = tests.formal.helpers.output_references.report(names)
    path = peri_scribe.report.markdown.render_markdown_report(prepared, directory)
    references = await asyncio.to_thread(report_references, path, len(names))
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.widgets.ReportViewerApp(),
    ) as session:
        viewer = session.app.query_one(peri_scribe.monitor.widgets.ReportViewer)
        await viewer.go(path)
        await session.refresh()
        check_navigation(viewer.document, references, monkeypatch)
        await session.refresh()
