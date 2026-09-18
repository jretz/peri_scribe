"""Exercise screenshot commands on their own screen and isolated output directory."""

import pathlib
import typing

import pytest_asyncio

import peri_scribe.monitor.screenshots
import tests.helpers.textual


type Session = tests.helpers.textual.Session[
    peri_scribe.monitor.screenshots.SnapshotApp
]


@pytest_asyncio.fixture
async def snapshot_session(tmp_path: pathlib.Path) -> typing.AsyncIterator[Session]:
    """Keep screenshot command behavior independent of the monitor's widgets.

    Args:
        tmp_path: The current test's isolated screenshot destination.

    Yields:
        A mounted snapshot screen and its owning application.
    """
    async with tests.helpers.textual.mounted(
        peri_scribe.monitor.screenshots.SnapshotApp(tmp_path),
    ) as session:
        yield session
