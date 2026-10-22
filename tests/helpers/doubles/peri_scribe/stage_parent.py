"""Start the actual public CLI with deterministic private child domain effects."""

import pathlib
import sys
import unittest.mock

import peri_scribe.main
import peri_scribe.supervision


def child_command(
    descriptor: int,
    request_path: pathlib.Path,
    response_path: pathlib.Path,
) -> list[str]:
    """Substitute only the child bootstrap, retaining the real transport protocol.

    Args:
        descriptor: Inherited production writer lease.
        request_path: Production serialized segment options.
        response_path: Production completed handoff destination.

    Returns:
        A fresh interpreter running the local stage fixture.
    """
    return [
        sys.executable,
        "-m",
        "tests.helpers.doubles.peri_scribe.stage_worker",
        str(descriptor),
        str(request_path),
        str(response_path),
    ]


def main() -> None:
    """Keep public option parsing, logging, leases and supervision active."""
    with unittest.mock.patch.object(
        peri_scribe.supervision,
        "child_command",
        child_command,
    ):
        peri_scribe.main.cli()


if __name__ == "__main__":
    main()
