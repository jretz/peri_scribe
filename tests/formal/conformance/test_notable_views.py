"""Complete notable selection follows active-owner ranking and evidence gates."""

import tests.formal.helpers.notable_views


def test_new_notable_fires_matches_complete_population_policy() -> None:
    cases = tests.formal.helpers.notable_views.population_cases()
    assert len(cases) == tests.formal.helpers.notable_views.POPULATION_CASE_COUNT
    tests.formal.helpers.notable_views.check_cases(cases)


def test_new_notable_fires_matches_all_signal_and_discovery_boundaries() -> None:
    cases = tests.formal.helpers.notable_views.signal_cases()
    assert len(cases) == tests.formal.helpers.notable_views.SIGNAL_CASE_COUNT
    tests.formal.helpers.notable_views.check_cases(cases)
