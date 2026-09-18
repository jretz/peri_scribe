"""Isolate component behavior from the monitor's complete layout and live state."""

import typing

import pytest_asyncio

import tests.helpers.doubles.peri_scribe.monitor.widgets
import tests.helpers.textual


type DividerSession = tests.helpers.textual.Session[
    tests.helpers.doubles.peri_scribe.monitor.widgets.DividerApp
]
type ReportSession = tests.helpers.textual.Session[
    tests.helpers.doubles.peri_scribe.monitor.widgets.ReportViewerApp
]


@pytest_asyncio.fixture
async def divider_session() -> typing.AsyncIterator[DividerSession]:
    """Keep pane sizing independent of the monitor's other views.

    Yields:
        Fresh horizontal and vertical dividers in an isolated terminal.
    """
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.widgets.DividerApp(),
    ) as session:
        yield session


@pytest_asyncio.fixture
async def report_session() -> typing.AsyncIterator[ReportSession]:
    """Exercise link handling against an actual mounted report.

    Yields:
        A report viewer and the event loop owning its Markdown children.
    """
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.widgets.ReportViewerApp(),
    ) as session:
        yield session
