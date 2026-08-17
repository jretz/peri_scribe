"""Unit tests for peri_scribe.retry — rate-limit detection and backoff."""

import http
import json

import pytest
import requests
import tenacity

import peri_scribe.retry


# Error payloads matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RETRY_AFTER_HEADER_SECONDS = 7
RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec."
            ),
        ],
    },
}
LOOSE_429_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Too many requests.",
    },
}

# JSON wire-format strings of the payloads, used to exercise the string fallback
# classification.
RATE_LIMIT_ERROR_STRING = json.dumps(RATE_LIMIT_ERROR_PAYLOAD)
LOOSE_429_ERROR_STRING = json.dumps(LOOSE_429_ERROR_PAYLOAD)


def test_rate_limit_retry_seconds_uses_server_hint() -> None:
    error = ValueError(RATE_LIMIT_ERROR_PAYLOAD)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == RATE_LIMIT_RETRY_AFTER_SECONDS
    )


def test_rate_limit_retry_seconds_uses_fallback_for_loose_429() -> None:
    error = ValueError(LOOSE_429_ERROR_PAYLOAD)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_rate_limit_retry_seconds_uses_server_hint_from_string() -> None:
    error = ValueError(RATE_LIMIT_ERROR_STRING)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == RATE_LIMIT_RETRY_AFTER_SECONDS
    )


def test_rate_limit_retry_seconds_uses_fallback_for_loose_429_string() -> None:
    error = ValueError(LOOSE_429_ERROR_STRING)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_rate_limit_retry_seconds_uses_retry_after_header() -> None:
    response = requests.Response()
    response.status_code = http.HTTPStatus.TOO_MANY_REQUESTS
    response.headers["Retry-After"] = str(RETRY_AFTER_HEADER_SECONDS)
    error = requests.exceptions.HTTPError("rate limited", response=response)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == RETRY_AFTER_HEADER_SECONDS
    )


def test_rate_limit_retry_seconds_uses_fallback_without_retry_after_header() -> None:
    response = requests.Response()
    response.status_code = http.HTTPStatus.TOO_MANY_REQUESTS
    error = requests.exceptions.HTTPError("rate limited", response=response)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_rate_limit_retry_seconds_uses_fallback_for_non_numeric_header() -> None:
    response = requests.Response()
    response.status_code = http.HTTPStatus.TOO_MANY_REQUESTS
    response.headers["Retry-After"] = "later"
    error = requests.exceptions.HTTPError("rate limited", response=response)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_rate_limit_retry_seconds_returns_none_for_other_http_errors() -> None:
    response = requests.Response()
    response.status_code = http.HTTPStatus.INTERNAL_SERVER_ERROR
    error = requests.exceptions.HTTPError("server error", response=response)
    assert peri_scribe.retry.rate_limit_retry_seconds(error) is None


def test_rate_limit_retry_seconds_returns_none_for_other_errors() -> None:
    error = RuntimeError("boom")
    assert peri_scribe.retry.rate_limit_retry_seconds(error) is None


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ConnectionError(
            "Connection broken: IncompleteRead(…)",
        ),
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


def failed_retry_state(error: Exception) -> tenacity.RetryCallState:
    """Build the retry state of a single failed attempt raising *error*.

    Returns:
        A retry state whose latest attempt raised *error*.
    """
    retry_state = tenacity.RetryCallState(
        retry_object=tenacity.Retrying(),
        fn=None,
        args=(),
        kwargs={},
    )
    retry_state.set_exception((type(error), error, error.__traceback__))
    return retry_state


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
    retry_state = failed_retry_state(ValueError(RATE_LIMIT_ERROR_PAYLOAD))
    assert peri_scribe.retry.retry_wait(retry_state) == RATE_LIMIT_RETRY_AFTER_SECONDS


def test_retry_wait_uses_fallback_for_loose_429() -> None:
    retry_state = failed_retry_state(ValueError(LOOSE_429_ERROR_PAYLOAD))
    assert (
        peri_scribe.retry.retry_wait(retry_state)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_retry_wait_uses_exponential_backoff() -> None:
    retry_state = failed_retry_state(
        requests.exceptions.ConnectionError("Connection broken"),
    )
    retry_state.attempt_number = 3
    assert peri_scribe.retry.retry_wait(retry_state) == pytest.approx(
        peri_scribe.retry.BACKOFF_BASE_SECONDS * 4,
    )


def test_retry_wait_caps_backoff_at_maximum() -> None:
    retry_state = failed_retry_state(
        requests.exceptions.ConnectionError("Connection broken"),
    )
    retry_state.attempt_number = 20
    assert (
        peri_scribe.retry.retry_wait(retry_state)
        == peri_scribe.retry.BACKOFF_MAXIMUM_SECONDS
    )


def test_last_error_returns_failed_exception() -> None:
    error = ValueError("boom")
    assert peri_scribe.retry.last_error(failed_retry_state(error)) is error


def test_last_error_raises_without_outcome() -> None:
    retry_state = tenacity.RetryCallState(
        retry_object=tenacity.Retrying(),
        fn=None,
        args=(),
        kwargs={},
    )
    with pytest.raises(AssertionError, match="failed attempt"):
        peri_scribe.retry.last_error(retry_state)
