"""Stateless oracle reuse follows the currently compiled executable."""

from __future__ import annotations

import pathlib
import typing
import unittest.mock

import tests.formal.helpers.oracle
import tests.formal.helpers.process


if typing.TYPE_CHECKING:
    import pytest


def test_repeated_oracle_requests_follow_the_current_executable(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oracle = tests.formal.helpers.oracle
    path = tmp_path / "lean" / ".lake" / "build" / "bin" / "oracle"
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\nprintf '41\\n'\n")
    path.chmod(0o700)
    monkeypatch.setattr(oracle, "DIRECTORY", tmp_path)
    process = tests.formal.helpers.process
    launched = unittest.mock.Mock(wraps=process.run)
    monkeypatch.setattr(process, "run", launched)

    first = oracle.evaluate(["request"])
    assert first == [(41,)]
    first.clear()
    assert oracle.evaluate(["request"]) == [(41,)]
    launched.assert_called_once()
    launched.reset_mock()

    replacement = path.with_name("rebuilt")
    replacement.write_text("#!/bin/sh\nprintf '42\\n'\n")
    replacement.chmod(0o700)
    replacement.replace(path)

    assert oracle.evaluate(["request"]) == [(42,)]
    launched.assert_called_once()
