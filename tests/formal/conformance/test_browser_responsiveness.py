"""The response watchdog agrees with every checked bounded timer history."""

import json
import pathlib
import shutil

import tests.formal.helpers.observers
import tests.formal.helpers.process
import tests.formal.helpers.tlc


def test_create_response_monitor_refines_tlc_histories(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.tlc.states(
        "BrowserResponsiveness",
        "BrowserResponsiveness",
        tmp_path,
    )
    assert len(states) == tests.formal.helpers.observers.BROWSER_RESPONSE_STATE_COUNT
    cases = [
        {
            "trace": tests.formal.helpers.observers.sequence(state["trace"]),
            "clock": int(state["clock"]),
            "lastResponse": int(state["lastResponse"]),
            "warning": state["warning"] == "TRUE",
        }
        for state in states
    ]
    traces = {
        tuple(tests.formal.helpers.observers.sequence(state["trace"]))
        for state in states
    }
    assert ("response", "advance", "advance", "reject", "response") in traces
    assert ("delay", "delay", "dispatch", "response", "advance") in traces
    node = shutil.which("node")
    assert node is not None, "Run mise formal-conformance to provide Node"
    result = tests.formal.helpers.process.run(
        [node, str(pathlib.Path(__file__).parents[1] / "helpers/browser_response.mjs")],
        standard_input=json.dumps(cases),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"checked": len(cases) * 3}
