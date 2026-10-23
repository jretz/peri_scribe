"""Complete notable selection follows active-owner ranking and evidence gates."""

import pytest

import tests.formal.helpers.notable_views


@pytest.mark.parametrize("holding", [False, True])
def test_new_notable_fires_matches_complete_population_policy(*, holding: bool) -> None:
    cases = tests.formal.helpers.notable_views.population_cases()
    assert len(cases) == tests.formal.helpers.notable_views.POPULATION_CASE_COUNT
    tests.formal.helpers.notable_views.check_cases(cases, holding=holding)


@pytest.mark.parametrize("holding", [False, True])
def test_new_notable_fires_matches_all_signal_and_discovery_boundaries(
    *,
    holding: bool,
) -> None:
    cases = tests.formal.helpers.notable_views.signal_cases()
    assert len(cases) == tests.formal.helpers.notable_views.SIGNAL_CASE_COUNT
    tests.formal.helpers.notable_views.check_cases(cases, holding=holding)
