"""Publication-local boundary storage follows complete checked operation prefixes."""

import pathlib

import pytest

import kml_io.fragments
import tests.formal.helpers.boundary_spill
import tests.formal.helpers.corpus
import tests.formal.helpers.ordered_workers


def test_boundary_spool_matches_every_checked_prefix(tmp_path: pathlib.Path) -> None:
    states = tests.formal.helpers.corpus.states(
        "BoundarySpill",
        "BoundarySpill",
        tmp_path,
    )
    assert {int(state["limit"]) for state in states} == {1, 2}
    assert {
        action
        for state in states
        for action in tests.formal.helpers.ordered_workers.numbers(state["trace"])
    } == {1, 2, 11, 12, 13, 21, 22, 23, 31, 32, 33, 41, 42}
    tests.formal.helpers.boundary_spill.replay_prefixes(states)


def test_replay_prefixes_runs_changed_history_sensitive_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = (
        ((), "new", "{}", "0", "0"),
        ((1,), "active", "{}", "0", "0"),
        ((1, 11), "active", "{1}", "2", "0"),
        ((1, 33), "active", "{}", "0", "0"),
        ((1, 33, 11), "active", "{1}", "2", "0"),
        ((1, 11, 31), "active", "{1}", "2", "1"),
        ((1, 33, 11, 31), "active", "{1}", "2", "1"),
    )
    states = [
        {
            "trace": f"<<{', '.join(map(str, trace))}>>",
            "scope": f'"{scope}"',
            "stored": stored,
            "used": used,
            "result": result,
            "limit": "1",
            "disabled": "FALSE",
            "corrupt": "{}",
        }
        for trace, scope, stored, used, result in history
    ]
    reads: set[kml_io.fragments.BoundarySpool] = set()
    original = kml_io.fragments.BoundarySpool.get

    def history_sensitive(
        spool: kml_io.fragments.BoundarySpool,
        key: str,
    ) -> bytes | None:
        """Make an earlier miss influence a later read without changing spool bytes.

        Returns:
            The actual payload, or a miss when reading key one after key three.
        """
        if key == "3":
            reads.add(spool)
        return None if key == "1" and spool in reads else original(spool, key)

    monkeypatch.setattr(kml_io.fragments.BoundarySpool, "get", history_sensitive)
    with pytest.raises(AssertionError, match=r"<<1, 33, 11, 31>>"):
        tests.formal.helpers.boundary_spill.replay_prefixes(states)
