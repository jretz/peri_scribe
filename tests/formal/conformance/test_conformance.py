"""Require complete native collections and phase reports for successful evidence."""

import pytest

import tests.formal.helpers.conformance


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "missing-worker",
        "extra-worker",
        "different-collection",
        "duplicate-item",
        "missing-call",
        "duplicate-call",
        "failure",
        "skip",
        "unexpected-item",
    ],
)
def test_complete_requires_all_workers_and_exact_passing_protocols(change: str) -> None:
    evidence = tests.formal.helpers.conformance.Evidence(
        workers=2,
        inventories={"gw0": ("first", "second"), "gw1": ("first", "second")},
        reports=[
            (nodeid, phase, "passed", None)
            for nodeid in ("first", "second")
            for phase in ("setup", "call", "teardown")
        ],
    )
    match change:
        case "missing-worker":
            del evidence.inventories["gw1"]
        case "extra-worker":
            evidence.inventories["gw2"] = evidence.inventories["gw0"]
        case "different-collection":
            evidence.inventories["gw1"] = ("second", "first")
        case "duplicate-item":
            evidence.inventories = {
                "gw0": ("first", "first"),
                "gw1": ("first", "first"),
            }
        case "missing-call":
            evidence.reports.pop(1)
        case "duplicate-call":
            evidence.reports.append(evidence.reports[1])
        case "failure":
            evidence.reports[1] = ("first", "call", "failed", None)
        case "skip":
            evidence.reports[1] = ("first", "call", "skipped", None)
        case "unexpected-item":
            evidence.reports[1] = ("outside", "call", "passed", None)
        case _:
            assert change == "none"
    assert evidence.complete() == (change == "none")


def test_complete_rejects_empty_collections() -> None:
    evidence = tests.formal.helpers.conformance.Evidence(
        workers=2,
        inventories={"gw0": (), "gw1": ()},
    )
    assert not evidence.complete()
