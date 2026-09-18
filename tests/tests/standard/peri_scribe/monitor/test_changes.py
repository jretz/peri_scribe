"""Directory watches survive folder creation and recoverable backend errors."""

import asyncio
import pathlib
import unittest.mock

import pytest

import peri_scribe.monitor.changes
import tests.helpers.doubles.peri_scribe.monitor.changes
from peri_scribe.units import units


def test_directories_excludes_unrelated_source_trees(tmp_path: pathlib.Path) -> None:
    for name in ("logs", "sources", "derived", "reports", "maps"):
        (tmp_path / name).mkdir()
    assert peri_scribe.monitor.changes.directories(tmp_path) == (
        tmp_path,
        tmp_path / "logs",
        tmp_path / "reports",
        tmp_path / "maps",
    )


@pytest.mark.asyncio
async def test_watch_restarts_when_a_watched_directory_is_created(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = asyncio.Event()
    first = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
        stopped,
        tmp_path / "logs",
    )
    second = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(stopped)
    watch = unittest.mock.Mock(side_effect=[first, second])
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    result = await tests.helpers.doubles.peri_scribe.monitor.changes.collect(
        tmp_path,
        stopped,
    )
    assert result == [None, None]
    assert watch.call_args_list[0].args == (tmp_path,)
    assert watch.call_args_list[1].args == (tmp_path, tmp_path / "logs")
    assert watch.call_args.kwargs["recursive"] is False


@pytest.mark.parametrize(
    "error",
    [OSError("Unavailable"), RuntimeError("Backend failed")],
)
@pytest.mark.asyncio
async def test_watch_retries_after_backend_failure(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    stopped = asyncio.Event()
    notifications = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
        stopped,
    )
    watch = unittest.mock.Mock(side_effect=[error, notifications])
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    monkeypatch.setattr(
        peri_scribe.monitor.changes,
        "RECONCILE_INTERVAL",
        0 * units.seconds,
    )
    assert (
        await tests.helpers.doubles.peri_scribe.monitor.changes.collect(
            tmp_path,
            stopped,
        )
    ) == [None]


@pytest.mark.asyncio
async def test_watch_stops_during_error_retry_wait(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = asyncio.Event()
    watch = unittest.mock.Mock(side_effect=OSError("Unavailable"))
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    assert (
        await tests.helpers.doubles.peri_scribe.monitor.changes.stop_during_retry(
            tmp_path,
            stopped,
        )
    ) == []
    watch.assert_called_once()


@pytest.mark.asyncio
async def test_watch_retries_until_year_directory_exists(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "2026"
    stopped = asyncio.Event()
    notifications = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
        stopped,
    )
    watch = unittest.mock.Mock(return_value=notifications)
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    monkeypatch.setattr(
        peri_scribe.monitor.changes,
        "RECONCILE_INTERVAL",
        0 * units.seconds,
    )
    assert (
        await tests.helpers.doubles.peri_scribe.monitor.changes.create_during_retry(
            directory,
            stopped,
        )
    ) == [None]
    assert [call.args for call in watch.call_args_list] == [(directory,)]


@pytest.mark.asyncio
async def test_watch_stops_during_missing_directory_retry_wait(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = asyncio.Event()
    watch = unittest.mock.Mock(
        return_value=tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
            stopped,
        ),
    )
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    assert (
        await tests.helpers.doubles.peri_scribe.monitor.changes.stop_during_retry(
            tmp_path / "2026",
            stopped,
        )
    ) == []
    watch.assert_not_called()


@pytest.mark.asyncio
async def test_watch_reattaches_when_a_watched_directory_is_replaced(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    stopped = asyncio.Event()
    first = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(
        stopped,
        changed=directory,
    )
    second = tests.helpers.doubles.peri_scribe.monitor.changes.notifications(stopped)
    watch = unittest.mock.Mock(side_effect=[first, second])
    monkeypatch.setattr(peri_scribe.monitor.changes.watchfiles, "awatch", watch)
    result = await tests.helpers.doubles.peri_scribe.monitor.changes.collect(
        tmp_path,
        stopped,
    )
    assert result == [None, None]
    assert [call.args for call in watch.call_args_list] == [(tmp_path, directory)] * 2
