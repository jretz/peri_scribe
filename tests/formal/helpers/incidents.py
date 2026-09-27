"""Keep numeric oracle provenance attached to real incident source rows."""

import datetime

import peri_scribe.incidents
import tests.formal.helpers.areas


def measurement(
    value: int,
    source: int,
    confirmation: int,
    *,
    observed: int = 10,
    column: str = "incident_size",
    confirmed: bool | None = None,
) -> peri_scribe.incidents.IncidentUpdate:
    """Expose source identity and report evidence independently to reconciliation.

    Args:
        value: The supplied measurement in its native units.
        source: The source identifier transported by the Lean oracle.
        confirmation: Formal-report seconds after the epoch, or -1 for missing.
        observed: Observation seconds after the epoch.
        column: The supplied measurement field.
        confirmed: An explicit confirmation flag, or None to follow report presence.

    Returns:
        An update retaining the exact evidence supplied to the formal policy.
    """
    epoch = tests.formal.helpers.areas.TIME
    return peri_scribe.incidents.IncidentUpdate(
        observation_time=epoch + datetime.timedelta(seconds=observed),
        report_time=(
            None
            if confirmation < 0
            else epoch + datetime.timedelta(seconds=confirmation)
        ),
        confirmed=confirmation >= 0 if confirmed is None else confirmed,
        source=str(source),
        source_file=f"{source}.gpkg",
        serial=source,
        measurements={column: float(value)},
    )


def evidence(update: peri_scribe.incidents.IncidentUpdate) -> tuple[int, int, int]:
    """Compare selected measurement and its provenance as one indivisible result.

    Args:
        update: The winning source update returned by the implementation.

    Returns:
        The exact value, source identity, and formal-report timestamp.
    """
    return (
        int(update.measurements["incident_size"]),
        int(update.source),
        (
            -1
            if update.report_time is None
            else int(
                (update.report_time - tests.formal.helpers.areas.TIME).total_seconds(),
            )
        ),
    )
