"""Provide data builders and stand-ins for main publication tests."""

from __future__ import annotations

import dataclasses
import pathlib
import typing

import tests.main_stubs
import tests.peri_scribe.publication_helpers


if typing.TYPE_CHECKING:
    import peri_scribe.publication


NOW = tests.peri_scribe.publication_helpers.NOW


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
    stubs: tests.main_stubs.RunStubs
    indexed: list[pathlib.Path]
    inputs: peri_scribe.publication.Collection
    output: pathlib.Path
