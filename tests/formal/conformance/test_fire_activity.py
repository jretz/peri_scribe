"""The cumulative activity classifier agrees with the proved raw-history reference."""

import tests.formal.helpers.fire_activity


def test_growth_window_matches_past_only_peak_reference() -> None:
    assert (
        len(tests.formal.helpers.fire_activity.histories())
        == tests.formal.helpers.fire_activity.HISTORY_COUNT
    )
    tests.formal.helpers.fire_activity.check_windows()


def test_active_status_matches_cumulative_policy_reference() -> None:
    tests.formal.helpers.fire_activity.check_statuses()


def test_active_status_compares_independent_streams() -> None:
    tests.formal.helpers.fire_activity.check_independent_streams()


def test_growth_window_preserves_unit_meaning() -> None:
    tests.formal.helpers.fire_activity.check_unit_adapter()
