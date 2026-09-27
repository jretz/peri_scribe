import datetime
import itertools

import peri_scribe.areas
import tests.formal.helpers.areas
import tests.formal.helpers.oracle


def test_report_can_take_over_matches_lean_at_policy_and_evidence_boundaries() -> None:
    cases = tests.formal.helpers.areas.takeover_cases()
    expected = tests.formal.helpers.oracle.evaluate([case.command() for case in cases])
    for case, result in zip(cases, expected, strict=True):
        assert tests.formal.helpers.areas.implementation_takeover(case) == bool(
            result[0],
        ), case


def test_accepted_reports_matches_lean_decrease_and_confirmation_policy() -> None:
    cases = list(itertools.product((-1, 0, 9, 10, 40, 100), range(130), (False, True)))
    expected = tests.formal.helpers.oracle.evaluate([
        f"accept {previous} {current} {int(confirmed)}"
        for previous, current, confirmed in cases
    ])
    time = tests.formal.helpers.areas.TIME
    for (previous, current, confirmed), result in zip(cases, expected, strict=True):
        latest = tests.formal.helpers.areas.report(
            current,
            time + datetime.timedelta(seconds=1),
            confirmed=confirmed,
        )
        reports = (
            (latest,)
            if previous < 0
            else (tests.formal.helpers.areas.report(previous, time), latest)
        )
        accepted = peri_scribe.areas.accepted_reports(
            reports,
            peri_scribe.areas.DEFAULT_POLICY,
        )
        assert (accepted[-1] is latest) == bool(result[0]), (
            previous,
            current,
            confirmed,
        )
