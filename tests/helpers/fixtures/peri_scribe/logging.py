"""Isolate logging tests with explicit fixtures."""

from __future__ import annotations

import typing

import pytest

import peri_scribe.logging


if typing.TYPE_CHECKING:
    import structlog


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
