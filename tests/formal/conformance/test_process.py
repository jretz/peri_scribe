import asyncio
import unittest.mock

import pytest

import tests.formal.helpers.process


def test_run_timeout_drains_output_before_waiting_for_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = unittest.mock.create_autospec(asyncio.subprocess.Process, instance=True)
    process.returncode = None
    process.communicate.side_effect = [
        TimeoutError("proof tool deadline"),
        (b"buffered output", b"buffered diagnostics"),
    ]
    process.wait.side_effect = AssertionError("Undrained pipes can block process exit")
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        unittest.mock.AsyncMock(return_value=process),
    )
    with pytest.raises(TimeoutError, match="proof tool deadline"):
        tests.formal.helpers.process.run(["proof-tool"])
    process.kill.assert_called_once_with()
    assert process.communicate.await_args_list == [
        unittest.mock.call(b""),
        unittest.mock.call(),
    ]
