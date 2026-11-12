"""Record complete conformance evidence from the standard pytest-xdist controller."""

from __future__ import annotations

import argparse
import collections
import collections.abc
import dataclasses
import hashlib
import json
import pathlib
import time
import typing

import pytest

import tests.formal.helpers.session
import tests.helpers.ordinary_lanes


if typing.TYPE_CHECKING:
    import xdist.workermanage


type Report = tuple[str, str | None, str, str | None]


@dataclasses.dataclass(kw_only=True)
class Evidence:
    """Observe native collections and reports without changing worker scheduling."""

    workers: int
    inventories: dict[str, tuple[str, ...]] = dataclasses.field(default_factory=dict)
    events: list[dict[str, object]] = dataclasses.field(default_factory=list)
    reports: list[Report] = dataclasses.field(default_factory=list)

    def pytest_xdist_node_collection_finished(
        self,
        node: xdist.workermanage.WorkerController,
        ids: collections.abc.Sequence[str],
    ) -> None:
        """Keep every complete native collection for the final inventory comparison."""
        self.inventories[node.gateway.id] = tuple(ids)
        self.events.append({
            "event": "collection",
            "worker": node.gateway.id,
            "count": len(ids),
            "sha256": hashlib.sha256(
                json.dumps(ids, separators=(",", ":")).encode(),
            ).hexdigest(),
            "monotonic_ns": time.monotonic_ns(),
        })

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Retain actual setup, call and teardown outcomes from native pytest."""
        self.reports.append((
            report.nodeid,
            report.when,
            report.outcome,
            getattr(report, "wasxfail", None),
        ))

    def complete(self) -> bool:
        """Require matching full collections and one passing protocol per item.

        Returns:
            Whether every intended worker collected every completed item.
        """
        if len(self.inventories) != self.workers:
            return False
        reference = next(iter(self.inventories.values()))
        return (
            bool(reference)
            and len(set(reference)) == len(reference)
            and all(items == reference for items in self.inventories.values())
            and collections.Counter(self.reports)
            == collections.Counter(
                (nodeid, phase, "passed", None)
                for nodeid in reference
                for phase in ("setup", "call", "teardown")
            )
        )


def main() -> int:
    """Run the stock worker pool and preserve its complete native evidence.

    Returns:
        The native session's exit status, rejecting incomplete successful evidence.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=pathlib.Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--workers", type=int, required=True)
    options = parser.parse_args()
    directory = options.directory.resolve(strict=True)
    corpus = tests.formal.helpers.session.directory()
    assert corpus is not None
    root = pathlib.Path(__file__).resolve().parents[3]
    evidence = Evidence(workers=options.workers)
    arguments = [
        "-c",
        str(root / "tests/formal/pytest.ini"),
        "--use-pristine-targets",
        str(root / "tests/formal/conformance"),
        "--basetemp",
        str(corpus / "pytest-temp"),
        "-o",
        "tmp_path_retention_policy=failed",
        "-n",
        str(options.workers),
        f"--junitxml={directory / 'formal.xml'}",
    ]
    status = 1
    try:
        status = int(pytest.main(arguments, plugins=[evidence]))
        if status == 0 and not evidence.complete():
            status = 1
        return status
    finally:
        tests.helpers.ordinary_lanes.publish(
            directory / "formal.json",
            {
                "status": status,
                "arguments": arguments,
                "initial": options.workers,
                "source": options.source,
                "ordered_ids": next(iter(evidence.inventories.values()), ()),
                "workers": sorted(evidence.inventories),
                "events": evidence.events,
                "reports": evidence.reports,
            },
        )


if __name__ == "__main__":
    raise SystemExit(main())
