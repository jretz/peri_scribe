"""The production browser protocol refines every checked refresh transaction."""

import json
import pathlib
import shutil

import tests.formal.helpers.corpus
import tests.formal.helpers.observers
import tests.formal.helpers.process


def test_load_updates_refines_tlc_refresh_transactions(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "BrowserRefresh",
        "BrowserRefresh",
        tmp_path,
    )
    cases = tests.formal.helpers.observers.browser_cases(states)
    assert len(cases) == tests.formal.helpers.observers.BROWSER_CASE_COUNT
    node = shutil.which("node")
    assert node is not None, "Run mise formal-conformance to provide Node"
    result = tests.formal.helpers.process.run(
        [node, str(pathlib.Path(__file__).parents[1] / "helpers/browser_refresh.mjs")],
        standard_input=json.dumps(cases),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"checked": len(cases) * 2}
