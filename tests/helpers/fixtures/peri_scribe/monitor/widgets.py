"""Isolate component behavior from the monitor's complete layout and live state."""

import typing

import pytest

import tests.helpers.doubles.peri_scribe.monitor.widgets
import tests.helpers.textual


type DividerSession = tests.helpers.textual.Session[
    tests.helpers.doubles.peri_scribe.monitor.widgets.DividerApp
]
type ReportSession = tests.helpers.textual.Session[
    tests.helpers.doubles.peri_scribe.monitor.widgets.ReportViewerApp
]


@pytest.fixture
def divider_session() -> typing.Iterator[DividerSession]:
    """Keep pane sizing independent of the monitor's other views.

    Yields:
        Fresh horizontal and vertical dividers in an isolated terminal.
    """
    with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.widgets.DividerApp(),
    ) as session:
        yield session


@pytest.fixture
def report_session() -> typing.Iterator[ReportSession]:
    """Exercise link handling against an actual mounted report.

    Yields:
        A report viewer and the event loop owning its Markdown children.
    """
    with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.widgets.ReportViewerApp(),
    ) as session:
        yield session
