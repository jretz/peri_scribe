"""Inspect main publication behavior with shared test utilities."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import tests.helpers.doubles.peri_scribe.main
import tests.helpers.factories.peri_scribe.publication


if typing.TYPE_CHECKING:
    import peri_scribe.publication

NOW = tests.helpers.factories.peri_scribe.publication.NOW


OPTIONS = ["--publish-threshold", "25 acre", "5m"]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Scenario:
    """Only external operations are stubbed; state and the decision remain real.

    Args:
        year: The isolated year directory containing test sources and outputs.
        stubs: Pipeline substitutes that record which stages run.
        indexed: The year directories for which deferred indexing was requested.
        inputs: The downloaded source inventory supplied to the publication gate.
        output: The local KMZ path used to validate the publication checkpoint.
    """

    year: pathlib.Path
    stubs: tests.helpers.doubles.peri_scribe.main.RunStubs
    indexed: list[pathlib.Path]
    inputs: peri_scribe.publication.Collection
    output: pathlib.Path
