"""Construct real publication inputs for each abstract gate condition."""

import dataclasses
import datetime

import peri_scribe.publication
import tests.helpers.factories.peri_scribe.publication


REASONS = (
    peri_scribe.publication.Reason.NO_PUBLICATION,
    peri_scribe.publication.Reason.EVACUATIONS,
    peri_scribe.publication.Reason.SOURCE_HISTORY,
    peri_scribe.publication.Reason.NO_CHANGES,
    peri_scribe.publication.Reason.AREA,
    peri_scribe.publication.Reason.TIMER,
    peri_scribe.publication.Reason.BELOW_THRESHOLD,
)
INTERVAL_SECONDS = 300


@dataclasses.dataclass(frozen=True, kw_only=True)
class Gate:
    """Inputs at the boundary between publication inventory and gate policy."""

    valid: bool
    evacuations: bool
    history: bool
    pending: bool
    mapping: bool
    elapsed: int

    def command(self) -> str:
        """Represent the timer boundary using the five-minute test threshold.

        Returns:
            The oracle request corresponding to this publication inventory.
        """
        values = (
            self.valid,
            self.evacuations,
            self.history,
            self.pending,
            self.mapping,
            self.elapsed >= INTERVAL_SECONDS,
        )
        return "gate " + " ".join(str(int(value)) for value in values)


def implementation_decision(case: Gate) -> peri_scribe.publication.Decision:
    """Exercise gate precedence through real inventory and area comparisons.

    Args:
        case: The abstract gate conditions to represent with source observations.

    Returns:
        The complete implementation decision.
    """
    baseline = tests.helpers.factories.peri_scribe.publication.mapping(100)
    candidate = tests.helpers.factories.peri_scribe.publication.mapping(
        125 if case.mapping else 124,
        serial=2,
    )
    published = tests.helpers.factories.peri_scribe.publication.publication(baseline)
    collection = tests.helpers.factories.peri_scribe.publication.collection(
        baseline,
        *((candidate,) if case.pending else ()),
    )
    stamp = peri_scribe.publication.FileStamp(size=2, modified_nanoseconds=2)
    collection = collection.model_copy(
        update={
            "evacuations": stamp if case.evacuations else None,
            "files": {
                **collection.files,
                **({baseline.source_file: stamp} if case.history else {}),
            },
        },
    )
    return peri_scribe.publication.decide(
        collection,
        published if case.valid else None,
        tests.helpers.factories.peri_scribe.publication.THRESHOLD,
        tests.helpers.factories.peri_scribe.publication.NOW
        + datetime.timedelta(seconds=case.elapsed),
    )
