import asyncio

import pytest

import tests.formal.helpers.process
import tests.formal.helpers.runner_parallel


def test_run_models_admits_four_tools_and_cleans_private_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = tests.formal.helpers.runner_parallel.ExecutionProbe()
    monkeypatch.setattr(tests.formal.helpers.process, "execute", probe.execute)
    passed, held = asyncio.run(
        asyncio.wait_for(
            tests.formal.helpers.runner_parallel.held_run(probe),
            timeout=5,
        ),
    )
    expected = {model.config for model in tests.formal.helpers.runner_parallel.models()}
    assert passed
    assert held == {f"model-{index}" for index in range(4)}
    assert set(probe.directories) == expected
    assert len(set(probe.directories.values())) == len(expected)
    assert all(not path.exists() for path in probe.directories.values())
    assert set(probe.java_directories) == expected
    assert len(set(probe.java_directories.values())) == len(expected)
    assert all(not path.exists() for path in probe.java_directories.values())
    assert not probe.active


def test_run_models_attempts_all_models_after_failure_timeout_and_launch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = tests.formal.helpers.runner_parallel.ExecutionProbe(
        outcomes={
            "model-0": None,
            "model-1": TimeoutError("deadline"),
            "model-2": OSError("cannot start Java"),
        },
    )
    monkeypatch.setattr(tests.formal.helpers.process, "execute", probe.execute)
    passed, _ = asyncio.run(
        asyncio.wait_for(
            tests.formal.helpers.runner_parallel.held_run(probe),
            timeout=5,
        ),
    )
    assert not passed
    assert set(probe.directories) == {
        model.config for model in tests.formal.helpers.runner_parallel.models()
    }
    assert all(not path.exists() for path in probe.directories.values())
    assert set(probe.java_directories) == set(probe.directories)
    assert all(not path.exists() for path in probe.java_directories.values())
    assert not probe.active
    assert not probe.cancelled


def test_run_models_cancels_active_tools_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = tests.formal.helpers.runner_parallel.ExecutionProbe()
    monkeypatch.setattr(tests.formal.helpers.process, "execute", probe.execute)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            asyncio.wait_for(
                tests.formal.helpers.runner_parallel.cancelled_run(probe),
                timeout=5,
            ),
        )
    assert probe.cancelled == {f"model-{index}" for index in range(4)}
    assert set(probe.directories) == probe.cancelled
    assert all(not path.exists() for path in probe.directories.values())
    assert set(probe.java_directories) == probe.cancelled
    assert all(not path.exists() for path in probe.java_directories.values())
    assert not probe.active
