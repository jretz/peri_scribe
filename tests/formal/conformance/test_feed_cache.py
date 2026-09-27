"""The authoritative snapshot replay must survive every modeled cache gap."""

from __future__ import annotations

import pathlib
import typing

import structlog.testing

import tests.formal.helpers.feed_cache
import tests.formal.helpers.tlc


if typing.TYPE_CHECKING:
    import pytest


def test_write_current_state_matches_every_checked_cache_candidate(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = tests.formal.helpers.tlc.states(
        "FeedCache",
        "FeedCache",
        tmp_path / "model",
    )
    candidates = [state for state in states if state["phase"] == '"writing"']
    assert len(candidates) == 4**3 * 3 * 4 * 2
    with structlog.testing.capture_logs():
        for state in candidates:
            tests.formal.helpers.feed_cache.replay(
                state,
                tmp_path / "source",
                monkeypatch,
            )
