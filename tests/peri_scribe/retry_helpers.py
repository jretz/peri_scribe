"""Provide data builders and stand-ins for retry tests."""

import json

import requests
import tenacity

from tests.conftest import LOOSE_429_ERROR_PAYLOAD, RATE_LIMIT_ERROR_PAYLOAD


RETRY_AFTER_HEADER_IN_SECONDS = 7


RATE_LIMIT_ERROR_STRING = json.dumps(RATE_LIMIT_ERROR_PAYLOAD)


LOOSE_429_ERROR_STRING = json.dumps(LOOSE_429_ERROR_PAYLOAD)


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


def raise_disconnected_query() -> None:
    """Simulate a disconnected query after retries are exhausted.

    Raises:
        requests.exceptions.ConnectionError: Always, to exercise serializable failure
            logging.
    """
    message = "Disconnected"
    raise requests.exceptions.ConnectionError(message)
