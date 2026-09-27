"""Recent-window seeks and context restoration share the checked partition."""

import pathlib
import tempfile

import tests.formal.helpers.monitor_context
import tests.formal.helpers.tlc


def test_context_records_refines_tlc_partitions(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.tlc.states(
        "MonitorContext",
        "MonitorContext",
        tmp_path,
    )
    assert len(states) == tests.formal.helpers.monitor_context.STATE_COUNT
    checked = 0
    for state in states:
        tests.formal.helpers.monitor_context.replay_partition(state)
        if state["checked"] == "{}":
            for command_context in (False, True):
                with tempfile.TemporaryDirectory(dir=tmp_path) as directory:
                    tests.formal.helpers.monitor_context.replay_reader(
                        state,
                        pathlib.Path(directory),
                        command_context=command_context,
                    )
            checked += 1
    assert checked == tests.formal.helpers.monitor_context.HISTORY_COUNT
