"""Provide diagnostic replacements whose event identities overlap older snapshots."""

import peri_scribe.monitor.display
import peri_scribe.monitor.model
import tests.helpers.factories.peri_scribe.monitor.events


def records(
    identifier: str,
    *,
    count: int = 300,
) -> peri_scribe.monitor.display.Records:
    """Prepare enough rows to expose cooperative widget application boundaries.

    Args:
        identifier: The command owning every prepared event.
        count: The number of diagnostic rows in the replacement.

    Returns:
        Complete content with sequence identities beginning at one.
    """
    state = peri_scribe.monitor.model.append_records(
        peri_scribe.monitor.model.State(),
        tuple(
            tests.helpers.factories.peri_scribe.monitor.events.record(
                "Starting command" if index == 0 else f"Replacement event {index}",
                run_id=identifier,
            )
            for index in range(count)
        ),
    )
    filtering = peri_scribe.monitor.display.Filter(minimum_level="debug", query="")
    return peri_scribe.monitor.display.prepare(
        state,
        state.runs[-1],
        tests.helpers.factories.peri_scribe.monitor.events.BRANCHES,
        filtering,
        filtering,
    )
