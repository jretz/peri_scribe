import peri_scribe.fires.scoring
import tests.formal.helpers.numerical_policy
import tests.formal.helpers.oracle


def test_finite_binary64_arithmetic_matches_integer_rounding_model() -> None:
    cases = tests.formal.helpers.numerical_policy.arithmetic_cases()
    expected_count = 1564
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "arithmetic|" + tests.formal.helpers.numerical_policy.arguments(*case)
            for case in cases
        ],
        executable="oracleNumericalPolicy",
    )
    for (left, right), result in zip(cases, expected, strict=True):
        assert (
            tuple(
                tests.formal.helpers.numerical_policy.integer(value)
                for value in (
                    left - right,
                    left * right,
                    left / right if right else 0.0,
                )
            )
            == result
        )


def test_mapping_decision_matches_rounded_conversion_and_tolerance_boundaries() -> None:
    cases = tests.formal.helpers.numerical_policy.publications()
    expected_count = 3750
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oracleNumericalPolicy",
    )
    for case, result in zip(cases, expected, strict=True):
        assert case.result() == result, case


def test_report_can_take_over_matches_fractional_unit_and_ratio_boundaries() -> None:
    cases = tests.formal.helpers.numerical_policy.takeovers()
    expected_count = 1740
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [case.command() for case in cases],
        executable="oracleNumericalPolicy",
    )
    for case, (result,) in zip(cases, expected, strict=True):
        assert case.result() == bool(result), case


def test_accepted_reports_matches_fractional_decrease_boundaries() -> None:
    cases = tests.formal.helpers.numerical_policy.corrections()
    expected_count = 48
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "accept|"
            + tests.formal.helpers.numerical_policy.arguments(
                previous,
                current,
                10.0,
                1.25,
            )
            + f" {int(confirmed)}"
            for previous, current, confirmed in cases
        ],
        executable="oracleNumericalPolicy",
    )
    for (previous, current, confirmed), (result,) in zip(cases, expected, strict=True):
        assert tests.formal.helpers.numerical_policy.corrected(
            previous,
            current,
            confirmed=confirmed,
        ) == bool(result)


def test_tiered_points_matches_exact_fractional_comparisons() -> None:
    cases = tests.formal.helpers.numerical_policy.tier_cases()
    expected_count = 80
    assert len(cases) == expected_count
    expected = tests.formal.helpers.oracle.evaluate(
        [
            "tier|"
            + str(tests.formal.helpers.numerical_policy.integer(value))
            + " "
            + " ".join(
                f"{tests.formal.helpers.numerical_policy.integer(tier.threshold)} "
                f"{tier.score}"
                for tier in tiers
            )
            for value, tiers in cases
        ],
        executable="oracleNumericalPolicy",
    )
    for (value, tiers), (result,) in zip(cases, expected, strict=True):
        assert peri_scribe.fires.scoring.tiered_points(value, tiers) == result
