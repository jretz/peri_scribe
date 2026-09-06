"""Retry utilities."""

from __future__ import annotations

import http
import re
import typing

import requests
import structlog
import tenacity

from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint


logger = structlog.get_logger()

# Matches the server-suggested retry-after delay in an ArcGIS REST API rate-limit error
# detail, e.g. "Retry after 8 sec".
RETRY_AFTER_DETAIL_PATTERN = re.compile(r"Retry[ ]after[ ](\d+)[ ]sec")

# Matches any ArcGIS REST API error body that carries a 429 code (loose fallback when
# the error is a string rather than a structured payload).
LOOSE_429_PATTERN = re.compile(r"""['\"]code['\"]\s*:\s*429""")

# Matches an ArcGIS REST API error body that carries a 429 code followed by the
# server-suggested retry-after delay (string fallback).
RATE_LIMIT_ERROR_PATTERN = re.compile(
    r"""(?x)
    ['\"]code['\"]\s*:\s*429
    .*
    Retry[ ]after[ ](\d+)[ ]sec
""",
)

DEFAULT_MAX_RETRIES = 4
FALLBACK_RETRY = 60 * units.seconds

# Base and cap for exponential backoff on transient network errors.
BACKOFF_BASE = 2.0 * units.seconds
BACKOFF_MAXIMUM = 30.0 * units.seconds

# Exponential backoff for transient network errors, so successive attempts wait
# progressively longer and give the server time to recover.
BACKOFF_WAIT = tenacity.wait_exponential(
    multiplier=BACKOFF_BASE.m_as("seconds"),
    max=BACKOFF_MAXIMUM.m_as("seconds"),
)

# Exception types for transient network or protocol failures that are worth retrying:
# connection errors (connection broken/reset/aborted, RemoteDisconnected,
# ProtocolError), timeouts (read and connect), and chunked-encoding errors
# (IncompleteRead).
TRANSIENT_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def rate_limit_from_payload(payload: dict[str, object]) -> pint.Quantity[float] | None:
    """Return the delay encoded in an ArcGIS rate-limit payload, or None.

    Args:
        payload: The error payload dict whose ``error`` key carries the 429 code
            and, when present, a "Retry after N sec" detail.

    Returns:
        The server-suggested retry-after delay, the fallback delay when the payload has
        no retry-after hint, or None when the payload is not a rate-limit error.

    Examples:
        >>> rate_limit_from_payload(
        ...     {"error": {"code": 429, "details": ["Retry after 8 sec"]}},
        ... )
        <Quantity(8, 'second')>

        >>> rate_limit_from_payload({}) is None
        True
    """
    error_info = payload.get("error")
    if (
        not isinstance(error_info, dict)
        or error_info.get("code") != http.HTTPStatus.TOO_MANY_REQUESTS
    ):
        return None
    details = error_info.get("details", [])
    if not isinstance(details, list):
        return FALLBACK_RETRY
    for detail in details:
        rate_limit_match = RETRY_AFTER_DETAIL_PATTERN.search(str(detail))
        if rate_limit_match is not None:
            return int(rate_limit_match.group(1)) * units.seconds
    return FALLBACK_RETRY


def rate_limit_retry(error: BaseException) -> pint.Quantity[float] | None:
    """Return the delay before retrying after a rate-limit error.

    Rate-limit responses arrive in two forms. ArcGIS query errors are ``ValueError``
    instances whose first argument is the error payload dict (with ``error.code`` 429
    and a "Retry after N sec" detail). The requests-based last-edit timestamp check
    raises ``requests.exceptions.HTTPError`` carrying a 429 response. A string
    fallback handles any other error that carries a 429 code.

    Args:
        error: The exception raised by the failed attempt.

    Returns:
        The server-suggested retry-after delay, the fallback delay when the error is a
        429 response without a retry-after hint, or None when the error is not a
        rate-limit response.
    """
    payload = error.args[0] if isinstance(error, ValueError) and error.args else None
    if isinstance(payload, dict):
        return rate_limit_from_payload(payload)
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        if (
            response is not None
            and response.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
        ):
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None and retry_after.isdigit():
                return int(retry_after) * units.seconds
            return FALLBACK_RETRY
    error_string = str(error)
    rate_limit_match = RATE_LIMIT_ERROR_PATTERN.search(error_string)
    if rate_limit_match is not None:
        return int(rate_limit_match.group(1)) * units.seconds
    if LOOSE_429_PATTERN.search(error_string) is not None:
        return FALLBACK_RETRY
    return None


def is_transient_error(error: BaseException) -> bool:
    """Return True when *error* is likely a transient network failure.

    Args:
        error: The exception raised by the failed attempt.

    Returns:
        True when the error is a requests connection, timeout, or chunked-encoding
        error — the exception types requests raises for transient failures.
    """
    return isinstance(error, TRANSIENT_EXCEPTIONS)


def is_retryable_error(error: BaseException) -> bool:
    """Return True when *error* should trigger a retry.

    Rate-limit responses (HTTP 429 from the ArcGIS REST API) and transient network
    failures are retried; any other error propagates immediately.

    Args:
        error: The exception raised by the failed attempt.

    Returns:
        True when the attempt should be retried.
    """
    return rate_limit_retry(error) is not None or is_transient_error(error)


def retry_reason(error: BaseException) -> str:
    """Return the log message describing why *error* triggers a retry.

    Args:
        error: The exception raised by the failed attempt.

    Returns:
        The reason a retry is being made for *error*.

    Examples:
        >>> retry_reason(ValueError({"error": {"code": 429}}))
        'Rate-limited; retrying after server-suggested delay'
    """
    if rate_limit_retry(error) is not None:
        return "Rate-limited; retrying after server-suggested delay"
    return "Transient network error; retrying after backoff"


def last_error(retry_state: tenacity.RetryCallState) -> BaseException:
    """Return the exception raised by the latest failed attempt.

    Args:
        retry_state: The tenacity retry state holding the attempt outcome.

    Returns:
        The exception raised by the latest attempt.

    Raises:
        AssertionError: If the retry state has no attempt outcome yet.
    """
    outcome = retry_state.outcome
    if outcome is None:
        message = "retry callbacks only run after a failed attempt"
        raise AssertionError(message)
    return typing.cast("BaseException", outcome.exception())


def retry_wait(retry_state: tenacity.RetryCallState) -> float:
    """Return the delay before the next attempt after a failed one.

    Rate-limit errors use the server-suggested ``Retry after`` delay (or the fallback
    for a loose 429 response); other transient errors use exponential backoff from the
    attempt number. The delay is returned in seconds because tenacity reads it as a
    plain number of seconds.

    Args:
        retry_state: The tenacity retry state holding the failed attempt's
            exception and attempt number.

    Returns:
        The delay before the next attempt, in seconds.
    """
    retry = rate_limit_retry(last_error(retry_state))
    if retry is not None:
        return retry.m_as("seconds")
    return BACKOFF_WAIT(retry_state)


def run_with_retry[Result](
    feed_name: str,
    query: typing.Callable[[], Result],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Result:
    """Run *query*, retrying on transient and rate-limit errors.

    Rate-limit errors (HTTP 429 from the ArcGIS REST API) wait for the server-suggested
    ``Retry after`` delay (or the fallback for a loose 429 response). Other transient
    network errors wait with exponential backoff starting at ``BACKOFF_BASE`` and capped
    at ``BACKOFF_MAXIMUM``. Up to *max_retries* retries are made before the last error
    is re-raised.

    Args:
        feed_name: Human-readable feed identifier for log messages.
        query: The zero-argument callable that performs a single attempt.
        max_retries: Maximum number of retries before giving up.

    Returns:
        The result returned by *query*.

    Raises:
        The exception raised by the final failed attempt.
    """

    def log_before_sleep(retry_state: tenacity.RetryCallState) -> None:
        error = last_error(retry_state)
        logger.info(
            retry_reason(error),
            feed=feed_name,
            attempt=retry_state.attempt_number,
            retry_delay=retry_state.upcoming_sleep * units.seconds,
        )

    def log_exhaustion(retry_state: tenacity.RetryCallState) -> typing.NoReturn:
        error = last_error(retry_state)
        logger.error(
            "Retries exhausted",
            feed=feed_name,
            attempts=retry_state.attempt_number,
            reason=retry_reason(error),
            exc_info=error,
        )
        raise error

    retrying = tenacity.Retrying(
        retry=tenacity.retry_if_exception(is_retryable_error),
        wait=retry_wait,
        stop=tenacity.stop_after_attempt(max_retries + 1),
        before_sleep=log_before_sleep,
        retry_error_callback=log_exhaustion,
    )
    return retrying(query)
