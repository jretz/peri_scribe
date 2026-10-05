"""Isolate logging tests with explicit fixtures."""

from __future__ import annotations

import datetime
import typing

import pytest
import time_machine

import peri_scribe.logging


if typing.TYPE_CHECKING:
    import structlog


@pytest.fixture
def fixed_log_month() -> typing.Iterator[None]:
    """Keep assertions about one log file independent of calendar rollovers.

    Yields:
        Control while all events belong to the same month.
    """
    with time_machine.travel(
        datetime.datetime(2026, 9, 15, 12, tzinfo=datetime.UTC),
        tick=False,
    ):
        yield


@pytest.fixture
def cli_log_output(
    monkeypatch: pytest.MonkeyPatch,
    log_output: structlog.testing.LogCapture,
) -> structlog.testing.LogCapture:
    """Keep CLI invocations using the test's structured log capture.

    Args:
        monkeypatch: Replace dependencies and restore them after the test.
        log_output: Captured structured log entries for assertions.

    Returns:
        The captured CLI log entries.
    """
    monkeypatch.setattr(
        peri_scribe.logging,
        "configure_logging",
        lambda *_args, **_kwargs: None,
    )
    return log_output
