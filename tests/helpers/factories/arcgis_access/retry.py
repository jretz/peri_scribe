"""Build inputs for retry tests."""

from __future__ import annotations

import enum
import http
import json

import requests
import tenacity

from measurement_units import units


# Error messages matching the ArcGIS REST API 429 rate-limit response format.
RATE_LIMIT_RETRY_AFTER = 60 * units.seconds


RATE_LIMIT_ERROR_PAYLOAD = {
    "error": {
        "code": http.HTTPStatus.TOO_MANY_REQUESTS,
        "message": "Unable to perform query. Too many requests.",
        "details": [
            (
                "API calls quota exceeded (120975 request units)! maximum allowed "
                "request units (115200) per Minute. "
                f"Retry after {RATE_LIMIT_RETRY_AFTER.m_as('second')} sec."
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


RETRY_AFTER_HEADER_IN_SECONDS = 7


RATE_LIMIT_ERROR_STRING = json.dumps(RATE_LIMIT_ERROR_PAYLOAD)


LOOSE_429_ERROR_STRING = json.dumps(LOOSE_429_ERROR_PAYLOAD)


class AttemptOutcome(enum.Enum):
    """Distinguish outcomes that stop a query from failures that allow another try."""

    SUCCESS = "success"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    FATAL_ERROR = "fatal_error"


def query_effects(outcomes: list[AttemptOutcome], result: object) -> list[object]:
    """Make each attempted query observable without performing network requests.

    Args:
        outcomes: The sequence of successful and failed attempts to simulate.
        result: The value returned by a successful attempt.

    Returns:
        Mock side effects, with a successful terminal attempt after the sequence.
    """
    effects: dict[AttemptOutcome, object] = {
        AttemptOutcome.SUCCESS: result,
        AttemptOutcome.CONNECTION_ERROR: requests.exceptions.ConnectionError("Offline"),
        AttemptOutcome.TIMEOUT: requests.exceptions.Timeout("Timed out"),
        AttemptOutcome.RATE_LIMIT: ValueError({
            "error": {"code": 429, "details": ["Retry after 7 sec"]},
        }),
        AttemptOutcome.FATAL_ERROR: ValueError("Invalid query"),
    }
    return [effects[outcome] for outcome in outcomes] + [result]


def http_error(
    status_code: int,
    *,
    retry_after: str | None = None,
) -> requests.exceptions.HTTPError:
    """Build an HTTPError whose response has the given status and header.

    Args:
        status_code: The response status code.
        retry_after: The Retry-After header value, if any.

    Returns:
        The HTTPError.
    """
    response = requests.Response()
    response.status_code = status_code
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    return requests.exceptions.HTTPError("boom", response=response)


def failed_retry_state(error: Exception) -> tenacity.RetryCallState:
    """Build the retry state of a single failed attempt raising *error*.

    Args:
        error: Exception supplied for the selected failure case.

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
