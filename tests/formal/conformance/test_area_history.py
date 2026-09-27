import pytest

import peri_scribe.areas
import tests.formal.helpers.area_history
import tests.formal.helpers.areas
import tests.formal.helpers.oracle


def test_area_history_matches_lean_complete_selection_fold() -> None:
    cases = tests.formal.helpers.area_history.cases()
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oracleDomain",
    )
    for case, result in zip(cases, expected, strict=True):
        estimates = tests.formal.helpers.area_history.implementation(case)
        assert len(result) == len(estimates) * 5, case
        for estimate, fields in zip(
            estimates,
            zip(*[iter(result)] * 5, strict=True),
            strict=True,
        ):
            time, observed, area, provenance, reported = fields
            assert estimate.time.timestamp() == (
                tests.formal.helpers.areas.TIME.timestamp() + time
            ), case
            assert estimate.observation_time.timestamp() == (
                tests.formal.helpers.areas.TIME.timestamp() + observed
            ), case
            assert estimate.area.m_as("acres") == pytest.approx(area), case
            assert estimate.source_file == str(provenance), case
            assert (estimate.source is peri_scribe.areas.AreaSource.REPORTED) == bool(
                reported,
            ), case
