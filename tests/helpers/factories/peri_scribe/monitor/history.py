"""Independent run boundaries make recent-window context recovery testable."""

import datetime

import tests.helpers.factories.peri_scribe.monitor.status


def active_run_records(
    started: datetime.datetime,
    latest: datetime.datetime,
) -> tuple[dict[str, object], ...]:
    """Represent an active command whose progress omits its command name.

    Args:
        started: The command and fetch phase's original start time.
        latest: The time of the newest ordinary progress event.

    Returns:
        Production-shaped boundaries and progress sharing one run identity.
    """
    return (
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting command",
            command="run",
            when=started,
            process_id=1234,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Starting phase",
            phase="fetch",
            phase_path="fetch",
            when=started,
            process_id=1234,
        ),
        tests.helpers.factories.peri_scribe.monitor.status.record(
            "Source response received",
            phase="fetch",
            phase_path="fetch",
            when=latest,
            process_id=1234,
            source="wildfires",
        ),
    )
