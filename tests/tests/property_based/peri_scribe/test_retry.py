"""Unit tests for peri_scribe.retry — rate-limit detection and backoff."""

import unittest.mock

import hypothesis
import hypothesis.strategies
import pytest

import peri_scribe.retry
import tests.helpers.factories.peri_scribe.retry
import tests.helpers.strategies.peri_scribe.retry


# JSON wire-format strings of the payloads, used to exercise the string fallback
# classification.


@hypothesis.given(
    representations=tests.helpers.strategies.peri_scribe.retry.rate_limit_representations(),
)
def test_rate_limit_retry_agrees_for_payload_and_json_text(
    representations: tuple[dict[str, object], str],
) -> None:
    payload, text = representations
    assert peri_scribe.retry.rate_limit_retry(ValueError(text)) == (
        peri_scribe.retry.rate_limit_retry(ValueError(payload))
    )


@hypothesis.given(
    outcomes=hypothesis.strategies.lists(
        hypothesis.strategies.from_type(
            tests.helpers.factories.peri_scribe.retry.AttemptOutcome,
        ),
        max_size=10,
    ),
    maximum_retries=hypothesis.strategies.integers(0, 8),
)
def test_run_with_retry_stops_at_success_fatal_error_or_retry_limit(
    outcomes: list[tests.helpers.factories.peri_scribe.retry.AttemptOutcome],
    maximum_retries: int,
) -> None:
    result = object()
    effects = tests.helpers.factories.peri_scribe.retry.query_effects(outcomes, result)
    terminal_outcomes = {
        tests.helpers.factories.peri_scribe.retry.AttemptOutcome.SUCCESS,
        tests.helpers.factories.peri_scribe.retry.AttemptOutcome.FATAL_ERROR,
    }
    first_terminal = next(
        (
            index
            for index, outcome in enumerate(outcomes)
            if outcome in terminal_outcomes
        ),
        len(outcomes),
    )
    last_attempt = min(first_terminal, maximum_retries)
    expected = effects[last_attempt]
    query = unittest.mock.Mock(side_effect=effects)
    with unittest.mock.patch("time.sleep") as sleep:
        if isinstance(expected, Exception):
            with pytest.raises(type(expected)) as raised:
                peri_scribe.retry.run_with_retry(
                    "generated-feed",
                    query,
                    maximum_retries=maximum_retries,
                )
            assert raised.value is expected
        else:
            assert (
                peri_scribe.retry.run_with_retry(
                    "generated-feed",
                    query,
                    maximum_retries=maximum_retries,
                )
                is result
            )
    assert query.call_count == last_attempt + 1
    assert sleep.call_count == last_attempt
