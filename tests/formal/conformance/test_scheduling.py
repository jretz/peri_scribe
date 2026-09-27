import datetime
import itertools
import zoneinfo

import peri_scribe.sources.full_fetch_state
import tests.formal.helpers.oracle


def test_full_fetch_is_due_matches_lean_at_cadence_boundaries() -> None:
    cases = list(
        itertools.product(
            (0, 1, 3_600, 86_400),
            (False, True),
            (-86_400, -1, 0, 1, 3_599, 3_600, 3_601, 86_399, 86_400, 86_401),
        ),
    )
    expected = tests.formal.helpers.oracle.evaluate([
        f"due {interval} {int(previous)} {elapsed}"
        for interval, previous, elapsed in cases
    ])
    clock = datetime.datetime(2026, 11, 1, 9, tzinfo=datetime.UTC)
    pacific = zoneinfo.ZoneInfo("America/Los_Angeles")
    for (interval, previous, elapsed), result in zip(cases, expected, strict=True):
        last = clock - datetime.timedelta(seconds=elapsed)
        assert peri_scribe.sources.full_fetch_state.full_fetch_is_due(
            interval=datetime.timedelta(seconds=interval),
            current_time=clock.astimezone(pacific),
            last_full_fetch=last.astimezone(pacific) if previous else None,
        ) == bool(result[0]), (interval, previous, elapsed)
