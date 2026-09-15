"""Unit tests for peri_scribe.retry — rate-limit detection and backoff."""

import http
import json
import typing

import pytest
import requests
import tenacity

import peri_scribe.retry
import tests.peri_scribe.retry_helpers
from peri_scribe.units import units
from tests.conftest import (
    LOOSE_429_ERROR_PAYLOAD,
    RATE_LIMIT_ERROR_PAYLOAD,
    RATE_LIMIT_RETRY_AFTER,
)


if typing.TYPE_CHECKING:
    import structlog.testing


# JSON wire-format strings of the payloads, used to exercise the string fallback
# classification.


def test_rate_limit_retry_uses_server_hint() -> None:
    error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    assert peri_scribe.retry.rate_limit_retry(error) == RATE_LIMIT_RETRY_AFTER


def test_rate_limit_retry_uses_fallback_for_loose_429() -> None:
    error = ValueError(LOOSE_429_ERROR_PAYLOAD)
    assert peri_scribe.retry.rate_limit_retry(error) == peri_scribe.retry.FALLBACK_RETRY


def test_rate_limit_retry_uses_server_hint_from_string() -> None:
    error = ValueError(tests.peri_scribe.retry_helpers.RATE_LIMIT_ERROR_STRING)
    assert peri_scribe.retry.rate_limit_retry(error) == RATE_LIMIT_RETRY_AFTER


def test_rate_limit_retry_uses_fallback_for_loose_429_string() -> None:
    error = ValueError(tests.peri_scribe.retry_helpers.LOOSE_429_ERROR_STRING)
    assert peri_scribe.retry.rate_limit_retry(error) == peri_scribe.retry.FALLBACK_RETRY


def test_rate_limit_retry_uses_retry_after_header() -> None:
    error = tests.peri_scribe.retry_helpers.http_error(
        http.HTTPStatus.TOO_MANY_REQUESTS,
        retry_after=str(tests.peri_scribe.retry_helpers.RETRY_AFTER_HEADER_IN_SECONDS),
    )
    assert (
        peri_scribe.retry.rate_limit_retry(error)
        == tests.peri_scribe.retry_helpers.RETRY_AFTER_HEADER_IN_SECONDS * units.second
    )


def test_rate_limit_retry_uses_fallback_without_retry_after_header() -> None:
    error = tests.peri_scribe.retry_helpers.http_error(
        http.HTTPStatus.TOO_MANY_REQUESTS,
    )
    assert peri_scribe.retry.rate_limit_retry(error) == peri_scribe.retry.FALLBACK_RETRY


def test_rate_limit_retry_uses_fallback_for_non_numeric_header() -> None:
    error = tests.peri_scribe.retry_helpers.http_error(
        http.HTTPStatus.TOO_MANY_REQUESTS,
        retry_after="later",
    )
    assert peri_scribe.retry.rate_limit_retry(error) == peri_scribe.retry.FALLBACK_RETRY


def test_rate_limit_retry_returns_none_for_other_http_errors() -> None:
    error = tests.peri_scribe.retry_helpers.http_error(
        http.HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    assert peri_scribe.retry.rate_limit_retry(error) is None


def test_rate_limit_retry_returns_none_for_other_errors() -> None:
    error = RuntimeError("boom")
    assert peri_scribe.retry.rate_limit_retry(error) is None


def test_rate_limit_retry_returns_none_for_non_dict_payload_error() -> None:
    error = ValueError({"error": "boom"})
    assert peri_scribe.retry.rate_limit_retry(error) is None


def test_rate_limit_retry_returns_none_for_non_rate_limit_code() -> None:
    error = ValueError({"error": {"code": http.HTTPStatus.INTERNAL_SERVER_ERROR}})
    assert peri_scribe.retry.rate_limit_retry(error) is None


def test_rate_limit_retry_uses_fallback_for_non_list_details() -> None:
    error = ValueError({
        "error": {"code": http.HTTPStatus.TOO_MANY_REQUESTS, "details": "oops"},
    })
    assert peri_scribe.retry.rate_limit_retry(error) == peri_scribe.retry.FALLBACK_RETRY


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError("Connection broken: IncompleteRead(…)"),
        requests.exceptions.ConnectionError("Connection reset by peer"),
        requests.exceptions.ConnectionError("Connection aborted."),
        requests.exceptions.ConnectionError(
            "RemoteDisconnected('Remote end closed connection…')",
        ),
        requests.exceptions.ConnectionError("ProtocolError: …"),
        requests.exceptions.ChunkedEncodingError(
            "IncompleteRead(123 bytes read, 456 more expected)",
        ),
        requests.exceptions.ReadTimeout("ReadTimeout"),
        requests.exceptions.ConnectTimeout("ConnectTimeout"),
        requests.exceptions.Timeout("ReadTimeout"),
    ],
)
def test_is_transient_error_matches_transient_exception_types(
    error: BaseException,
) -> None:
    assert peri_scribe.retry.is_transient_error(error) is True


def test_is_transient_error_does_not_match_normal_errors() -> None:
    error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    assert peri_scribe.retry.is_transient_error(error) is False


def test_is_retryable_error_retries_rate_limit() -> None:
    error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    assert peri_scribe.retry.is_retryable_error(error) is True


def test_is_retryable_error_retries_transient() -> None:
    error = requests.exceptions.ConnectionError("Connection broken")
    assert peri_scribe.retry.is_retryable_error(error) is True


def test_is_retryable_error_rejects_other_errors() -> None:
    error = RuntimeError("boom")
    assert peri_scribe.retry.is_retryable_error(error) is False


def test_retry_reason_describes_rate_limit() -> None:
    error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    assert (
        peri_scribe.retry.retry_reason(error)
        == "Rate-limited; retrying after server-suggested delay"
    )


def test_retry_reason_describes_transient() -> None:
    error = requests.exceptions.ConnectionError("Connection broken")
    assert (
        peri_scribe.retry.retry_reason(error)
        == "Transient network error; retrying after backoff"
    )


def test_retry_wait_uses_server_hint() -> None:
    retry_state = tests.peri_scribe.retry_helpers.failed_retry_state(
        ValueError(RATE_LIMIT_ERROR_PAYLOAD),
    )
    assert peri_scribe.retry.retry_wait(retry_state) == RATE_LIMIT_RETRY_AFTER.m_as(
        "second",
    )


def test_retry_wait_uses_fallback_for_loose_429() -> None:
    retry_state = tests.peri_scribe.retry_helpers.failed_retry_state(
        ValueError(LOOSE_429_ERROR_PAYLOAD),
    )
    assert peri_scribe.retry.retry_wait(
        retry_state,
    ) == peri_scribe.retry.FALLBACK_RETRY.m_as("seconds")


def test_retry_wait_uses_exponential_backoff() -> None:
    retry_state = tests.peri_scribe.retry_helpers.failed_retry_state(
        requests.exceptions.ConnectionError("Connection broken"),
    )
    retry_state.attempt_number = 3
    assert peri_scribe.retry.retry_wait(retry_state) == pytest.approx(
        peri_scribe.retry.BACKOFF_BASE.m_as("seconds") * 4,
    )


def test_retry_wait_caps_backoff_at_maximum() -> None:
    retry_state = tests.peri_scribe.retry_helpers.failed_retry_state(
        requests.exceptions.ConnectionError("Connection broken"),
    )
    retry_state.attempt_number = 20
    assert peri_scribe.retry.retry_wait(
        retry_state,
    ) == peri_scribe.retry.BACKOFF_MAXIMUM.m_as("seconds")


def test_last_error_returns_failed_exception() -> None:
    error = ValueError("boom")
    assert (
        peri_scribe.retry.last_error(
            tests.peri_scribe.retry_helpers.failed_retry_state(error),
        )
        is error
    )


def test_last_error_raises_without_outcome() -> None:
    retry_state = tenacity.RetryCallState(
        retry_object=tenacity.Retrying(),
        fn=None,
        args=(),
        kwargs={},
    )
    with pytest.raises(AssertionError, match="failed attempt"):
        peri_scribe.retry.last_error(retry_state)


def test_run_with_retry_logs_serializable_traceback_on_exhaustion(
    log_output: structlog.testing.LogCapture,
) -> None:

    failing_query = tests.peri_scribe.retry_helpers.raise_disconnected_query

    with pytest.raises(requests.exceptions.ConnectionError, match="Disconnected"):
        peri_scribe.retry.run_with_retry("example", failing_query, max_retries=0)

    entry = json.loads(json.dumps(log_output.entries[0]))
    assert entry["event"] == "Retries exhausted"
    assert entry["attempts"] == 1
    assert "Traceback (most recent call last)" in entry["exception"]
    assert "ConnectionError: Disconnected" in entry["exception"]
