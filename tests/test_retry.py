"""Unit tests for peri_scribe.retry — rate-limit detection and backoff."""

import pytest

import peri_scribe.retry


# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER_SECONDS = 60
RATE_LIMIT_ERROR_BODY = (
    "{'error': {'code': 429, 'message': 'Unable to perform query. "
    "Too many requests.', 'details': ['API calls quota exceeded "
    "(120975 request units)! maximum allowed request units (115200) "
    f"per Minute. Retry after {RATE_LIMIT_RETRY_AFTER_SECONDS} sec.']}}"
)
LOOSE_429_ERROR_BODY = "{'error': {'code': 429, 'message': 'Too many requests.'}}"


def test_rate_limit_retry_seconds_uses_server_hint() -> None:
    error = ValueError(RATE_LIMIT_ERROR_BODY)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == RATE_LIMIT_RETRY_AFTER_SECONDS
    )


def test_rate_limit_retry_seconds_uses_fallback_for_loose_429() -> None:
    error = ValueError(LOOSE_429_ERROR_BODY)
    assert (
        peri_scribe.retry.rate_limit_retry_seconds(error)
        == peri_scribe.retry.FALLBACK_RETRY_SECONDS
    )


def test_rate_limit_retry_seconds_returns_none_for_other_errors() -> None:
    error = RuntimeError("boom")
    assert peri_scribe.retry.rate_limit_retry_seconds(error) is None


@pytest.mark.parametrize(
    "error_text",
    [
        "IncompleteRead(123 bytes read, 456 more expected)",
        "Connection broken: IncompleteRead(…)",
        "Connection reset by peer",
        "Connection aborted.",
        "RemoteDisconnected('Remote end closed connection…')",
        "ChunkedEncodingError: …",
        "ProtocolError: …",
        "ReadTimeout",
        "ConnectTimeout",
    ],
)
def test_is_transient_error_matches_transient_patterns(error_text: str) -> None:
    error = ValueError(error_text)
    assert peri_scribe.retry.is_transient_error(error) is True


def test_is_transient_error_does_not_match_normal_errors() -> None:
    error = ValueError(RATE_LIMIT_ERROR_BODY)
    assert peri_scribe.retry.is_transient_error(error) is False


def test_compute_backoff_returns_base_on_first_attempt() -> None:
    assert (
        peri_scribe.retry.compute_backoff(1) == peri_scribe.retry.BACKOFF_BASE_SECONDS
    )


def test_compute_backoff_doubles_each_attempt() -> None:
    base = peri_scribe.retry.BACKOFF_BASE_SECONDS
    assert peri_scribe.retry.compute_backoff(2) == pytest.approx(base * 2)
    assert peri_scribe.retry.compute_backoff(3) == pytest.approx(base * 4)


def test_compute_backoff_caps_at_maximum() -> None:
    assert (
        peri_scribe.retry.compute_backoff(20)
        == peri_scribe.retry.BACKOFF_MAXIMUM_SECONDS
    )
