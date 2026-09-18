"""Exercise live status controls independently of file collection and log views."""

import typing

import pytest

import peri_scribe.monitor.status_widgets
import tests.helpers.doubles.peri_scribe.monitor.status_widgets
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.textual


type Session = tests.helpers.textual.Session[
    tests.helpers.doubles.peri_scribe.monitor.status_widgets.StatusApp
]


@pytest.fixture
def status_session() -> typing.Iterator[Session]:
    """Start status controls without observations or available artifacts.

    Yields:
        An isolated status pane whose evidence can be supplied directly.
    """
    with tests.helpers.textual.mounted(
        tests.helpers.doubles.peri_scribe.monitor.status_widgets.StatusApp(),
    ) as session:
        pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
        session.call(
            pane.show_view,
            tests.helpers.factories.peri_scribe.monitor.status.view(),
        )
        yield session
